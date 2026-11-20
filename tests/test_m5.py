"""Executable plans, revision triggers, pure resumes, fair shared entry and caps."""

import json
from copy import deepcopy
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import pytest

from gradmatch.agent import Execution, Task
from gradmatch.catalog import DEFAULT_SEED, M35_SEED, load_seed
from gradmatch.config import load_settings
from gradmatch.constraints import evidence_ids
from gradmatch.planning import PlanDraft, Planner
from gradmatch.service import export_session, start_task
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.web_reader import FetchError
from scripts.m5_fixtures import AS_OF, FixtureProvider, plan, step

UW = "uw-ece-msece-pmp-seattle"


def run(session, provider, **kwargs):
    programs, sources = load_seed(kwargs.pop("seed", DEFAULT_SEED))
    return start_task(
        session,
        request_id=kwargs.pop("request_id", str(uuid4())),
        programs=programs,
        sources=sources,
        settings=replace(load_settings(), enabled=False),
        as_of=kwargs.pop("as_of", AS_OF),
        strategy=kwargs.pop("strategy", "plan"),
        provider=provider,
        **kwargs,
    )


def test_normal_plan_executes_and_rerun_reuses_without_paid_nodes():
    session = Session(profile=tiering_profile())
    provider = FixtureProvider()
    result = run(session, provider, request_id="initial")
    assert (
        result["status"] == "insufficient_evidence" and not result["validation_errors"]
    )
    state = result["task_usage"]["plan"]
    assert state["replans"] == 0 and state["revisions"][0]["status"] == "completed"
    assert all(s["status"] == "done" for s in state["revisions"][0]["steps"])
    assert [p for p, _ in provider.calls] == ["plan", "rank"]
    assert [o["tool"] for o in result["task_usage"]["tool_log"]] == [
        "search_programs",
        "check_constraints",
        "rank_programs",
        "validate_shortlist",
    ]
    assert [p["program_id"] for p in result["recommendations"]] == [
        "cmu-msaii-pittsburgh"
    ]
    replay = run(
        session, provider, request_id="initial", changes={"tuition_budget_usd": "1"}
    )
    assert replay is result and len(provider.calls) == 2
    reused = run(session, provider)
    assert reused["model_calls"] == 0 and len(provider.calls) == 2
    assert reused["task_usage"]["plan"]["replans"] == 0
    # Previously exported snapshots must not mutate as later revisions progress.
    assert state == result["task_usage"]["plan"]
    json.dumps(export_session(session))


@pytest.mark.parametrize("budget,kept", [("139000", True), ("100000", False)])
def test_budget_change_replans_with_current_checks_and_preserves_trace(budget, kept):
    session = Session(profile=tiering_profile())
    provider = FixtureProvider()
    first = run(session, provider)
    second = run(session, provider, message="Change my tuition budget to " + budget)
    state = second["task_usage"]["plan"]
    revision = state["revisions"][-1]
    assert second["task_id"] == first["task_id"] and second["model_calls"] == 2
    assert state["replans"] == 1 and revision["reason_code"] == "PROFILE_UPDATED"
    assert revision["profile_version"] == session.profile.profile_version
    assert revision["status"] == "completed" and all(
        s["status"] == "done" for s in revision["steps"]
    )
    assert bool(second["recommendations"]) is kept
    assert not second["validation_errors"]
    context = provider.calls[2][1]
    assert not context["current_state"]["finish_allowed"]
    assert all(
        o["tool"] in {"search_programs", "fetch_official_page"}
        or o["profile_version"] == session.profile.profile_version
        for o in context["observations"]
    )
    assert first["task_usage"]["plan"]["replans"] == 0


def test_plan_question_interrupt_does_not_repay_on_empty_resume():
    first = plan(
        [
            step(
                "ask",
                "ask_user",
                requested=["research"],
                question="What research experience do you have?",
            )
        ],
        programs=[UW],
    )
    provider = FixtureProvider([first, plan(programs=[UW])])
    session = Session(profile=tiering_profile())
    before = run(session, provider)
    assert before["status"] == "needs_input" and len(provider.calls) == 1
    empty = run(session, provider)
    assert empty["status"] == "needs_input" and len(provider.calls) == 1
    after = run(
        session, provider, changes={"research": ["A fictional research project."]}
    )
    assert after["status"] == "insufficient_evidence" and len(provider.calls) == 3
    assert after["task_usage"]["plan"]["replans"] == 1
    revisions = after["task_usage"]["plan"]["revisions"]
    assert revisions[0]["steps"][0]["status"] == "done"
    assert revisions[1]["reason_code"] == "PROFILE_UPDATED"


@pytest.mark.parametrize(
    "mutation,code",
    [
        ("forward", "DEPENDENCY_MUST_PRECEDE_STEP"),
        ("duplicate", "DUPLICATE_STEP_OR_DEPENDENCY"),
        ("program", "UNKNOWN_OR_DUPLICATE_PROGRAM"),
        ("criterion", "INVALID_DONE_CRITERIA"),
        ("rank", "RANK_DEPENDS_ON_CHECKS"),
        ("source", "SOURCE_ONLY_FOR_FETCH"),
        ("after_rank", "RANK_THEN_FINAL_VALIDATION_REQUIRED"),
        ("ask", "INVALID_APPLICANT_QUESTION"),
    ],
)
def test_model_plan_is_checked_before_execution(mutation, code):
    programs, sources = load_seed()
    session = Session(profile=tiering_profile())
    task = Task(
        "plan",
        "snapshot",
        programs,
        sources,
        json.loads((PROJECT_ROOT / "config/agent.json").read_text()),
    )
    driver = Execution(
        task, session, replace(load_settings(), enabled=False), AS_OF, FixtureProvider()
    )
    value = plan([step("search", "search_programs")])
    if mutation == "forward":
        value["steps"][0]["depends_on"] = ["rank"]
    if mutation == "duplicate":
        value["steps"][1]["step_id"] = "search"
    if mutation == "program":
        value["steps"][0]["program_ids"] = ["invented-program"]
    if mutation == "criterion":
        value["steps"][0]["done_criteria"] = ["ranking_current"]
    if mutation == "rank":
        value["steps"][2]["depends_on"] = ["search"]
    if mutation == "source":
        value["steps"][0]["source_id"] = "https://attacker.example/"
    if mutation == "after_rank":
        value["steps"].insert(-1, step("late", "search_programs", ["rank"]))
    if mutation == "ask":
        value["steps"][0] = step(
            "ask", "ask_user", requested=["api_key"], question="Send the secret?"
        )
        value["steps"][1]["depends_on"] = ["ask"]
    with pytest.raises(ValueError, match=code):
        Planner(driver).validate(PlanDraft.model_validate(value))
    assert not task.tools and not task.models


def test_invalid_plans_stop_after_three_replans_and_never_claim_completion():
    invalid = plan()
    invalid["steps"][1]["depends_on"] = []
    provider = FixtureProvider([deepcopy(invalid) for _ in range(4)])
    session = Session(profile=tiering_profile())
    result = run(session, provider)
    assert result["status"] == "budget_exhausted"
    assert result["task_usage"]["stop_reason"] == "REPLAN_LIMIT"
    assert result["task_usage"]["plan"]["replans"] == 3
    assert [p for p, _ in provider.calls] == ["plan"] * 4
    assert not result["recommendations"]
    assert all(
        o["tool"] == "validate_shortlist" for o in result["task_usage"]["tool_log"]
    )
    assert (
        run(session, provider)["status"] == "budget_exhausted"
        and len(provider.calls) == 4
    )


def fixture_session(group="credits"):
    from test_m4 import live_fixture

    if group == "gpa":
        driver, p, source, args = live_fixture(
            "gpa",
            {
                "gpa": {
                    "minimum": "3.25",
                    "scale": "4",
                    "accepted_scopes": ["overall"],
                    "recommended": None,
                    "below_minimum_review_possible": False,
                    "no_hard_minimum": False,
                }
            },
            "The minimum overall GPA is 3.25 on a 4 point scale.",
        )
    else:
        driver, p, source, args = live_fixture()
    driver.task.strategy = "plan"
    driver.session.agent_task = driver.task
    return driver, p, source, args


def test_missing_credits_triggers_replan_then_planned_fetch_does_not_replan_again():
    driver, p, source, args = fixture_session()
    p.field_sources["credits"] = []
    provider = FixtureProvider(
        [
            plan(programs=[UW], fields=["tuition"]),
            plan(
                [
                    step(
                        "fetch",
                        "fetch_official_page",
                        programs=[UW],
                        fields=["credits"],
                        source=source.source_id,
                    )
                ],
                programs=[UW],
            ),
        ],
        extraction=driver.provider.facts,
    )
    result = run(driver.session, provider, data_mode="live", fetcher=driver.fetcher)
    state = result["task_usage"]["plan"]
    assert (
        state["replans"] == 1
        and state["revisions"][-1]["reason_code"] == "MISSING_EVIDENCE"
    )
    assert state["revisions"][-1]["status"] == "completed"
    assert result["task_usage"]["page_requests"] == 1
    assert result["task_usage"]["evidence_version"] == 1
    # GPA scope mismatch remains pending; it must not cause spurious evidence repairs.
    assert evidence_ids(p, "credits", driver.task.sources, driver.session.profile)
    assert [purpose for purpose, _ in provider.calls] == [
        "plan",
        "plan",
        "extract",
        "rank",
    ]
    assert result["validation_errors"] == []


@pytest.mark.parametrize("fault", ["page_failure", "missing_fact", "conflict"])
def test_faults_revise_from_observations_and_preserve_unknowns(fault):
    driver, p, source, args = fixture_session(
        "gpa" if fault == "conflict" else "credits"
    )
    facts = driver.provider.facts
    if fault == "missing_fact":
        facts = {**facts, "facts": [], "missing_fields": ["credits"]}
    provider = FixtureProvider(
        [
            plan(
                [
                    step(
                        "fetch",
                        "fetch_official_page",
                        programs=[UW],
                        fields=args["target_fields"],
                        source=source.source_id,
                    )
                ],
                programs=[UW],
            ),
            plan(programs=[UW]),
        ],
        extraction=facts,
    )
    called = []

    def blocked(url, hosts, **kwargs):
        called.append(url)
        kwargs["before_request"]()
        raise FetchError("ACCESS_DENIED")

    result = run(
        driver.session,
        provider,
        data_mode="live",
        fetcher=blocked if fault == "page_failure" else driver.fetcher,
    )
    state = result["task_usage"]["plan"]
    assert state["replans"] == 1 and state["revisions"][-1]["status"] == "completed"
    assert (
        state["revisions"][1]["reason_code"]
        == {
            "page_failure": "TOOL_FAILURE",
            "missing_fact": "MISSING_EVIDENCE",
            "conflict": "SOURCE_CONFLICT",
        }[fault]
    )
    assert state["revisions"][0]["steps"][0]["status"] == "failed"
    assert (
        result["task_usage"]["page_requests"] == 1 and result["validation_errors"] == []
    )
    assert not result["recommendations"]
    if fault == "page_failure":
        assert len(called) == 1
    if fault == "conflict":
        assert not evidence_ids(p, "gpa", driver.task.sources, driver.session.profile)


def test_date_changes_trigger_revision_but_unchanged_date_does_not():
    session = Session(profile=tiering_profile())
    provider = FixtureProvider()
    run(session, provider)
    result = run(session, provider, as_of=AS_OF + timedelta(days=1))
    assert (
        result["task_usage"]["plan"]["revisions"][-1]["reason_code"]
        == "ASSESSMENT_DATE_CHANGED"
    )
    count = len(provider.calls)
    run(session, provider, as_of=AS_OF + timedelta(days=1))
    assert len(provider.calls) == count


def test_model_cap_includes_planner_and_rank_and_reserved_validation_is_pure():
    programs, sources = load_seed()
    session = Session(profile=tiering_profile())
    provider = FixtureProvider()
    limits = json.loads((PROJECT_ROOT / "config/agent.json").read_text())
    limits["max_models"] = 1
    session.agent_task = Task("plan", "snapshot", programs, sources, limits)
    result = run(session, provider)
    assert result["status"] == "budget_exhausted" and len(provider.calls) == 1
    assert result["task_usage"]["stop_reason"] == "MODEL_CALL_LIMIT"
    assert any(
        s["status"] == "blocked"
        for s in result["task_usage"]["plan"]["revisions"][-1]["steps"]
    )


def test_three_strategies_share_entry_catalog_caps_and_validator():
    results = []
    for strategy in ["fixed", "react", "plan"]:
        results.append(
            run(
                Session(profile=tiering_profile()), FixtureProvider(), strategy=strategy
            )
        )
    assert all(r["validation_errors"] == [] for r in results)
    assert len({r["data_hash"] for r in results}) == 1
    assert all(
        r["task_usage"]["limits"] == results[0]["task_usage"]["limits"] for r in results
    )
    assert [[p["program_id"] for p in r["recommendations"]] for r in results] == [
        ["cmu-msaii-pittsburgh"]
    ] * 3
    assert all(
        r["model_status"] == "test_stub"
        and not any(u.get("actual_request") for u in r["usage"])
        for r in results
    )


def test_plan_state_is_private_to_session_and_cli_accepts_third_strategy():
    first = Session(profile=tiering_profile())
    second = Session(profile=tiering_profile())
    a = run(first, FixtureProvider())
    b = run(second, FixtureProvider())
    run(first, FixtureProvider(), changes={"tuition_budget_usd": "100000"})
    assert a["task_id"] != b["task_id"] and second.agent_task.plan_state.replans == 0
    assert "plan" in (PROJECT_ROOT / "scripts/run_task.py").read_text()


@pytest.mark.parametrize("kind", ["evidence", "request"])
def test_other_real_triggers_invalidate_previous_completion(kind):
    session = Session(profile=tiering_profile())
    provider = FixtureProvider()
    run(session, provider)
    before = session.profile.model_dump()
    kwargs = {}
    if kind == "evidence":
        session.agent_task.evidence_version += 1
    else:
        kwargs["message"] = (
            "Explain the remaining candidates. Do not change my profile."
        )
    result = run(session, provider, **kwargs)
    expected = "EVIDENCE_CHANGED" if kind == "evidence" else "USER_REQUEST_UPDATED"
    assert result["task_usage"]["plan"]["revisions"][-1]["reason_code"] == expected
    assert session.profile.model_dump() == before and result["model_calls"] == 2
    assert result["validation_errors"] == []


def test_validation_failure_triggers_one_repair_plan_and_keeps_failed_draft():
    class InvalidFirstRank(FixtureProvider):
        bad = True

        def generate(self, kind, purpose, payload, session):
            value = super().generate(kind, purpose, payload, session)
            if purpose == "rank" and self.bad:
                self.bad = False
                value.recommendations[0].tier = "Target"
            return value

    provider = InvalidFirstRank()
    session = Session(profile=tiering_profile())
    result = run(session, provider)
    revisions = result["task_usage"]["plan"]["revisions"]
    assert len(revisions) == 2 and revisions[1]["reason_code"] == "VALIDATION_FAILED"
    assert revisions[0]["steps"][-2]["status"] == "failed"
    assert (
        result["validation_errors"] == []
        and result["recommendations"][0]["tier"] == "Lottery"
    )
    assert [purpose for purpose, _ in provider.calls] == [
        "plan",
        "rank",
        "plan",
        "rank",
    ]


@pytest.mark.parametrize("fault", ["snapshot", "owner"])
def test_fetch_plan_cannot_bypass_mode_or_source_ownership(fault):
    driver, _, source, _ = fixture_session()
    if fault == "snapshot":
        driver.task.mode = "snapshot"
        expected = "FETCH_NOT_ALLOWED_IN_SNAPSHOT"
        pid = UW
    else:
        expected = "UNREGISTERED_PLAN_SOURCE"
        pid = "cmu-msaii-pittsburgh"
    draft = PlanDraft.model_validate(
        plan(
            [
                step(
                    "fetch",
                    "fetch_official_page",
                    programs=[pid],
                    fields=["credits"],
                    source=source.source_id,
                )
            ],
            programs=[pid],
        )
    )
    with pytest.raises(ValueError, match=expected):
        Planner(driver).validate(draft)
    assert not driver.task.pages and not driver.task.models


def test_fixture_export_cannot_be_accepted_as_actual_model_evidence(tmp_path):
    from scripts.verify_m5 import inspect_actual_session

    session = Session(profile=tiering_profile())
    provider = FixtureProvider()
    run(session, provider)
    run(session, provider, message="Change my tuition budget to 100000")
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(export_session(session)))
    proof = inspect_actual_session(path)
    assert proof["status"] == "failed" and not proof["checks"]["real_metered_requests"]


def test_disabled_model_never_claims_a_plan_or_model_backed_reuse():
    result = run(Session(profile=tiering_profile()), None)
    assert result["model_calls"] == 0 and result["model_status"] == "not_configured"
    assert result["task_usage"]["plan"] is None


def test_reloaded_equivalent_intake_compares_by_value_and_does_not_revise_profile():
    from gradmatch.constraints import check_constraints
    from gradmatch.schemas import Intake
    from gradmatch.session import questions

    class ReloadedIntake(Intake):
        pass

    profile = tiering_profile()
    profile.intake = ReloadedIntake(year=2027, term="fall")
    programs, sources = load_seed()
    program = next(p for p in programs if p.program_id == "cmu-msaii-pittsburgh")
    assert profile.intake != program.supported_intakes[0]
    report = check_constraints(profile, program, sources, as_of=AS_OF)
    assert next(c for c in report.checks if c.rule_id == "intake").status == "pass"
    assert next(c for c in report.checks if c.rule_id == "deadline").status == "pass"
    assert report.recommendation_ready and not questions(profile, programs, as_of=AS_OF)
    session = Session(profile=profile)
    version = profile.profile_version
    assert session.update({"intake": {"year": 2027, "term": "fall"}}) == []
    assert session.profile.profile_version == version


@pytest.mark.parametrize("strategy", ["fixed", "react", "plan"])
def test_recorded_status_correction_finishes_without_paid_repair(strategy):
    from gradmatch.ranking import RankingDraft
    from gradmatch.validation import blocking_validation_errors

    recorded = json.loads(
        (PROJECT_ROOT / "tests/fixtures/m5_status_correction.json").read_text(
            encoding="utf-8"
        )
    )["draft"]

    class ReplayProvider(FixtureProvider):
        def generate(self, kind, purpose, payload, session):
            result = super().generate(kind, purpose, payload, session)
            return (
                RankingDraft.model_validate(recorded) if purpose == "rank" else result
            )

    profile = tiering_profile()
    profile.profile_version = 3
    profile.tuition_budget_usd = "139000"
    session = Session(profile=profile)
    provider = ReplayProvider()
    # This recorded draft is bound to the immutable M3.5 catalog hash.
    result = run(session, provider, strategy=strategy, seed=M35_SEED)
    assert result["status"] == "insufficient_evidence" and result["validation_passed"]
    assert not blocking_validation_errors(result)
    assert [w["code"] for w in result["validation_warnings"]] == [
        "MODEL_STATUS_CORRECTED"
    ]
    assert result["validation_warnings"] == result["validation_errors"]
    assert [r["program_id"] for r in result["recommendations"]] == [
        "cmu-msaii-pittsburgh"
    ]
    assert session.agent_task.stopped == "finished"
    assert sum(purpose == "rank" for purpose, _ in provider.calls) == 1
    if strategy == "plan":
        assert (
            result["task_usage"]["plan"]["replans"] == 0 and result["model_calls"] == 2
        )


def test_turning_paid_calls_off_keeps_unchanged_reuse_description_accurate():
    session = Session(profile=tiering_profile())
    first = run(session, FixtureProvider())
    result = run(session, None)
    assert result["model_calls"] == 0 and result["model_status"] == "reused_validated"
    assert (
        "No new model request" in result["message"]
        and "have not run" not in result["message"]
    )
    assert result["task_usage"]["tool_calls"] == first["task_usage"]["tool_calls"]


@pytest.mark.parametrize("change", ["profile", "date"])
def test_disabled_followup_changes_recompute_rules_without_claiming_old_plan_reuse(
    change,
):
    session = Session(profile=tiering_profile())
    first = run(session, FixtureProvider())
    kwargs = (
        {"changes": {"tuition_budget_usd": "100000"}}
        if change == "profile"
        else {"as_of": AS_OF + timedelta(days=1)}
    )
    result = run(session, None, **kwargs)
    assert result["model_calls"] == 0 and result["model_status"] == "not_configured"
    assert result["task_usage"]["tool_calls"] > first["task_usage"]["tool_calls"]
    assert result["as_of_date"] == str(kwargs.get("as_of", AS_OF))
    assert result["profile_version"] == session.profile.profile_version
    if change == "profile":
        assert any(
            p["program_id"] == "cmu-msaii-pittsburgh" for p in result["excluded"]
        )
