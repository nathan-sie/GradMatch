"""M2 state, trust, metering and actual Streamlit workflow regressions (no paid calls)."""

from dataclasses import replace
from datetime import date
from decimal import Decimal
import hashlib
import json
import re
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

from gradmatch.catalog import import_catalog, load_seed
from gradmatch.config import estimate_cost, load_settings
from gradmatch.constraints import check_constraints
from gradmatch.providers import ModelUnavailable, OpenAIProvider, strict_schema
from gradmatch.ranking import RankingDraft, retrieve
from gradmatch.schemas import AdmissionEvidence, GoalFeature, ProgramRecord
from gradmatch.service import export_session, start_task
from gradmatch.session import ProfilePatch, Session, apply_patch, quick_patch, synthetic_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import data_hash, validate_shortlist
from test_m1 import fixture_catalog, profile


AS_OF = date(2026, 11, 15)


@pytest.fixture(autouse=True)
def no_paid_requests(monkeypatch):
    monkeypatch.setenv("MODEL_ENABLED", "false")


def settings():
    return load_settings()


def draft_for(payload, **changes):
    data = {"profile_version": payload["profile"]["profile_version"], "status": "insufficient_evidence",
        "recommendations": [], "pending_order": [p["program_id"] for p, r in zip(payload["programs"], payload["reports"]) if r["hard_checks_status"] != "fail"], "observations": []}
    data.update(changes)
    return RankingDraft.model_validate(data)


class Stub:
    def __init__(self, patch=None):
        self.calls = []
        self.patch = patch

    def generate(self, output_type, purpose, payload, session):
        self.calls.append((purpose, payload))
        session.usage.append({"call_id": f"stub-{len(self.calls)}", "purpose": purpose, "status": "test_stub",
            "model": "test-only", "input_tokens": None, "output_tokens": None,
            "cached_input_tokens": None, "reasoning_tokens": None, "estimated_cost_usd": None, "duration_ms": 0})
        return self.patch if purpose == "interpret" else draft_for(payload)


def run(session, *, provider=None, request_id="first", **kwargs):
    programs, sources = load_seed()
    return start_task(session, request_id=request_id, programs=programs, sources=sources,
        settings=settings(), as_of=AS_OF, provider=provider, **kwargs)


def test_missing_information_is_grouped_before_any_model_request():
    session, stub = Session(), Stub()
    result = run(session, provider=stub)
    assert result["status"] == "needs_input" and not stub.calls
    requested = {field for q in result["pending_questions"] for field in q["requested_fields"]}
    assert {"gpa", "tuition_budget_usd", "intake", "goal", "major"} <= requested


@pytest.mark.parametrize("message", ["Change my tuition budget to 50,000", "预算改成50000美元"])
def test_budget_patch_invalidates_old_checks_and_preserves_other_background(message):
    session, stub = Session(profile=synthetic_profile()), Stub()
    before_profile = session.profile.model_dump(mode="json")
    before = run(session, provider=stub)
    after = run(session, provider=stub, request_id="budget", message=message)
    assert session.profile.tuition_budget_usd == Decimal(50000)
    expected = {**before_profile, "tuition_budget_usd": "50000", "profile_version": 2}
    assert session.profile.model_dump(mode="json") == expected
    assert after["profile_version"] == 2 and after["model_calls"] == 1
    assert session.previous_result["profile_version"] == 1
    assert any(p["program_id"].startswith("uw-") for p in before["pending_verification"])
    removed = after["changes_from_previous"]["removed"]
    assert any(p["program_id"].startswith("uw-") and "budget" in " ".join(p["reasons"]) for p in removed)
    assert all(p["report"]["profile_version"] == 2 for p in after["pending_verification"])
    assert not after["recommendations"]


def test_noop_patch_does_not_increment_version_and_goal_update_preserves_budget():
    session = Session(profile=synthetic_profile())
    assert not session.update({"tuition_budget_usd": "70000"})
    assert session.profile.profile_version == 1
    session.update({"goal": "research"})
    assert session.profile.profile_version == 2 and session.profile.tuition_budget_usd == Decimal(70000)


def test_invalid_patch_is_atomic_and_cannot_override_version_or_invent_support():
    session = Session(profile=synthetic_profile())
    old = session.profile.model_copy(deep=True)
    patch = ProfilePatch(intent="update_profile", operations=[
        {"field": "tuition_budget_usd", "value_json": '"50000"', "explicit_span": "budget to 50000"},
        {"field": "gpa.value", "value_json": '"4.0"', "explicit_span": "budget to 50000"}],
        referenced_program_ids=[], ambiguous_fields=[])
    with pytest.raises(ValueError): apply_patch(session, patch, "budget to 50000")
    assert session.profile == old
    with pytest.raises(ValueError): session.update({"profile_version": 99})
    patch.operations[0].explicit_span = "a fabricated quote"
    with pytest.raises(ValueError): apply_patch(session, patch, "budget to 50000")


def test_ambiguous_total_budget_does_not_change_profile():
    patch = ProfilePatch(intent="update_profile", operations=[{"field": "tuition_budget_usd", "value_json": '"50000"',
        "explicit_span": "total budget is 50000 including living costs"}], referenced_program_ids=[], ambiguous_fields=[])
    session = Session(profile=synthetic_profile())
    result = run(session, provider=Stub(patch), message="My total budget is 50000 including living costs")
    assert result["status"] == "needs_input" and session.profile.tuition_budget_usd == 70000


def test_duplicate_request_and_plain_rerender_never_repeat_model_call():
    session, stub = Session(profile=synthetic_profile()), Stub()
    first = run(session, provider=stub, request_id="same")
    again = run(session, provider=stub, request_id="same")
    assert first is again and len(stub.calls) == 1


@pytest.mark.parametrize("intent", ["explain_previous", "answer_question", "update_profile"])
def test_followup_uses_current_profile_and_previous_ids_without_extra_changes(intent):
    patch = ProfilePatch(intent=intent, operations=[], referenced_program_ids=[], ambiguous_fields=[])
    session, stub = Session(profile=synthetic_profile()), Stub(patch)
    run(session, provider=stub)
    run(session, provider=stub, request_id="budget", message="Change my tuition budget to 50000")
    before = session.profile.model_copy(deep=True)
    result = run(session, provider=stub, request_id="explain", message="Which remaining candidates fit employment goals? Do not change my profile.")
    assert session.profile == before and result["model_calls"] == 2
    interpreted = stub.calls[-2][1]
    assert interpreted["profile"]["tuition_budget_usd"] == "50000" and interpreted["previous_programs"]
    assert all(p["program_id"] in result["retrieved_program_ids"] for p in interpreted["previous_programs"])
    assert "sources" not in interpreted
    ranking = stub.calls[-1][1]
    assert all(report["hard_checks_status"] != "fail" for report in ranking["reports"])
    assert set(ranking["allowed_pending_program_ids"]) == {p["program_id"] for p in ranking["programs"]}
    assert not set(ranking["allowed_pending_program_ids"]) & {p["program_id"] for p in ranking["excluded_summary"]}


def test_empty_patch_for_explicit_update_still_requests_clarification():
    patch = ProfilePatch(intent="update_profile", operations=[], referenced_program_ids=[], ambiguous_fields=[])
    session = Session(profile=synthetic_profile())
    result = run(session, provider=Stub(patch), message="Update my GPA to a better score")
    assert result["status"] == "needs_input" and session.profile.profile_version == 1


def test_unknown_user_answer_stays_unknown_and_no_data_is_assumed():
    session = Session()
    unknown = {"gpa", "tuition_budget_usd", "intake", "goal", "major", "english"}
    result = run(session, provider=Stub(), changes={"goal": None}, unknown_fields=unknown)
    assert result["status"] == "insufficient_evidence" and not result["recommendations"]
    assert session.profile.gpa is None and session.profile.tuition_budget_usd is None


def test_sessions_have_separate_profiles_logs_and_results():
    first, second = Session(profile=synthetic_profile()), Session(profile=synthetic_profile())
    run(first, provider=Stub(), message="Change my tuition budget to 50000")
    assert second.profile.tuition_budget_usd == 70000 and second.profile.profile_version == 1
    assert second.current_result is None and not second.usage and not second.messages
    assert first.session_id != second.session_id


def test_missing_api_configuration_gives_real_checks_and_never_fake_model_output():
    result = run(Session(profile=synthetic_profile()))
    assert result["model_status"] == "not_configured" and result["model_calls"] == 0
    assert result["pending_verification"] and not result["recommendations"]
    assert result["status"] != "completed"


def positive_fixture():
    program, sources = fixture_catalog(eligibility_review_complete=True)
    program.goal_features = [GoalFeature(feature_id="feature-capstone", goal="employment", statement="Synthetic capstone.", source_ids=["fixture-source"])]
    program.admission_evidence = [AdmissionEvidence(evidence_id=f"admit-{i}", kind="admitted_case", source_ids=["fixture-source"],
        cycle_year=2025, independence_key=f"case-{i}", gpa={"value": "3.5", "scale": "4", "scope": "last_60_semester"},
        major="CS", experience_dimensions=["work_experience"], permitted_tiers=["Target", "Safer"],
        statement="Synthetic admitted applicant.", reviewed=True) for i in [1, 2]]
    source = sources["fixture-source"]
    for group in ["remaining_eligibility", "goal_features", "admission_evidence"]:
        program.field_sources[group] = [source.source_id]
        source.field_groups.append(group)
        source.verified_values[group] = {"eligibility_review_complete": True} if group == "remaining_eligibility" else {group: program.model_dump(mode="json")[group]}
    applicant = profile(major="CS", goal="employment", work_experience=["Synthetic internship"],
        english={"version": "ielts_9", "total": "7", "subscores": {"speaking": "7"}, "test_date": "2025-11-01"})
    item = {"program_id": program.program_id, "tier": "Target", "goal_feature_ids": ["feature-capstone"],
        "tier_evidence_ids": ["admit-1", "admit-2"], "comparison_dimensions": ["gpa", "work_experience"],
        "lower_risk_rationale": None, "limitations": ["Synthetic evidence; not a real recommendation."]}
    draft = RankingDraft(profile_version=applicant.profile_version, status="completed", recommendations=[item], pending_order=[], observations=[])
    return program, sources, applicant, draft


def test_reviewed_positive_path_can_produce_formal_result_and_exact_cost():
    program, sources, applicant, draft = positive_fixture()
    result = validate_shortlist(draft, applicant, [program], [program], sources, as_of=AS_OF)
    assert result["status"] == "completed" and len(result["recommendations"]) == 1
    assert result["recommendations"][0]["checks"]["tuition"]["upper_usd"] == "48000"
    assert result["recommendations"][0]["citations"][0]["url"] == str(sources["fixture-source"].url)


@pytest.mark.parametrize("attack", ["fake_tier", "fake_goal", "duplicate_case", "unreviewed", "old_cycle", "unknown_eligibility", "over_budget", "stale_version", "wrong_program", "wrong_goal"])
def test_unsupported_or_stale_recommendations_are_blocked(attack):
    program, sources, applicant, draft = positive_fixture()
    if attack == "fake_tier": draft.recommendations[0].tier_evidence_ids = ["made-up"]
    if attack == "fake_goal": draft.recommendations[0].goal_feature_ids = ["made-up"]
    if attack == "duplicate_case": program.admission_evidence[1].independence_key = "case-1"
    if attack == "unreviewed": program.admission_evidence[0].reviewed = False
    if attack == "old_cycle": program.admission_evidence[0].cycle_year = 2000
    if attack == "unknown_eligibility": program.eligibility_review_complete = False
    if attack == "over_budget": applicant.tuition_budget_usd = Decimal(47000)
    if attack == "stale_version": draft.profile_version = 99
    if attack == "wrong_program": draft.recommendations[0].program_id = "not-retrieved"
    if attack == "wrong_goal": applicant.goal = "research"
    result = validate_shortlist(draft, applicant, [program], [program], sources, as_of=AS_OF)
    assert not result["recommendations"] and result["validation_errors"]


def test_duplicate_program_is_blocked_and_fake_observation_citation_is_not_shown():
    program, sources, applicant, draft = positive_fixture()
    draft.recommendations.append(draft.recommendations[0].model_copy(deep=True))
    draft.observations = [{"program_id": program.program_id, "rule_id": "gpa", "source_ids": ["forged"]}]
    draft = RankingDraft.model_validate(draft.model_dump())
    result = validate_shortlist(draft, applicant, [program], [program], sources, as_of=AS_OF)
    assert len(result["recommendations"]) == 1 and not result["observations"]
    assert any("DUPLICATE_PROGRAM" in error.get("codes", []) for error in result["validation_errors"])


def test_unknown_and_partial_retrieval_are_not_mislabeled_infeasible():
    programs, sources = load_seed()
    applicant = synthetic_profile()
    applicant.tuition_budget_usd = Decimal(0)
    result = validate_shortlist(None, applicant, programs, programs, sources, as_of=AS_OF)
    assert result["status"] == "insufficient_evidence" and result["pending_verification"]
    program, source, applicant, draft = positive_fixture()
    applicant.tuition_budget_usd = Decimal(0)
    result = validate_shortlist(None, applicant, [program], [program], source, as_of=AS_OF)
    assert result["status"] == "infeasible"
    other = program.model_copy(update={"program_id": "other-fixture"})
    result = validate_shortlist(None, applicant, [program, other], [program], source, as_of=AS_OF)
    assert result["status"] == "insufficient_evidence"


def test_model_status_is_recomputed_and_false_completed_is_never_accepted():
    programs, sources = load_seed()
    applicant = synthetic_profile()
    draft = RankingDraft(profile_version=1, status="completed", recommendations=[], pending_order=[], observations=[])
    result = validate_shortlist(draft, applicant, programs, programs, sources, as_of=AS_OF)
    assert result["status"] == "insufficient_evidence"
    assert any(e.get("code") == "MODEL_STATUS_CORRECTED" for e in result["validation_errors"])


def test_fixed_retrieval_is_stable_and_budget_change_rechecks_entire_known_set():
    programs, sources = load_seed()
    applicant = synthetic_profile()
    assert retrieve(applicant, programs, 8) == retrieve(applicant, list(reversed(programs)), 8)
    assert len(retrieve(applicant, programs, 8)) == len(programs)
    assert data_hash(programs, sources) == data_hash(list(reversed(programs)), dict(reversed(list(sources.items()))))


def test_provider_sends_strict_schema_without_tools_and_accounts_real_response_usage():
    captured = {}
    draft = RankingDraft(profile_version=1, status="insufficient_evidence", recommendations=[], pending_order=[], observations=[])
    def create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(model="gpt-5.4-mini-2026-03-17", id="synthetic-response", status="completed", output_text=draft.model_dump_json(),
            usage=SimpleNamespace(input_tokens=1000, output_tokens=100, input_tokens_details=SimpleNamespace(cached_tokens=200),
                output_tokens_details=SimpleNamespace(reasoning_tokens=0)))
    enabled = replace(settings(), enabled=True, api_key="TEST-ONLY-KEY")
    session = Session()
    provider = OpenAIProvider(enabled, client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    assert provider.generate(RankingDraft, "rank", {}, session) == draft
    assert captured["store"] is False and "tools" not in captured and "previous_response_id" not in captured
    assert captured["text"]["format"]["strict"] is True
    assert session.usage[0]["estimated_cost_usd"] == "0.001065"
    assert "TEST-ONLY-KEY" not in json.dumps(export_session(session)) and "TEST-ONLY-KEY" not in repr(enabled)


def test_provider_failure_still_records_one_attempt_and_never_retries():
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(model="gpt-5.4-mini-2026-03-17", id="incomplete", usage=None, status="incomplete", output_text="")
    session = Session()
    provider = OpenAIProvider(replace(settings(), enabled=True, api_key="TEST"), client=SimpleNamespace(responses=SimpleNamespace(create=create)))
    with pytest.raises(ModelUnavailable): provider.generate(RankingDraft, "rank", {}, session)
    assert len(calls) == 1 and len(session.usage) == 1 and session.usage[0]["status"] == "error"
    assert session.usage[0]["estimated_cost_usd"] is None


def test_cost_unknown_prices_stay_unknown_and_limits_block_before_call():
    config = settings()
    assert estimate_cost(config, "unpriced-model", 10, 20, 0) is None
    assert estimate_cost(config, config.model, None, 20, 0) is None
    session = Session(usage=[{}] * 20)
    with pytest.raises(ModelUnavailable, match="limit"):
        OpenAIProvider(replace(config, enabled=True, api_key="TEST")).generate(RankingDraft, "rank", {}, session)


def test_structured_schemas_use_required_closed_objects():
    for schema in [strict_schema(RankingDraft), strict_schema(ProfilePatch)]:
        def check(node):
            if isinstance(node, dict):
                if node.get("type") == "object":
                    assert node["additionalProperties"] is False
                    assert set(node["required"]) == set(node.get("properties", {}))
                for value in node.values(): check(value)
            elif isinstance(node, list):
                for value in node: check(value)
        check(schema)


def test_m2_real_page_empty_sample_budget_rerender_reset_and_english(tmp_path, monkeypatch):
    database = tmp_path / "catalog.db"
    import_catalog(database=database)
    monkeypatch.setenv("GRADMATCH_DB_PATH", str(database))
    before_hash = hashlib.sha256(database.read_bytes()).hexdigest()
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=20).run()
    assert not app.exception
    app.button(key="m2_generate").click().run()
    assert not app.exception and app.session_state["m2_last_response"]["status"] == "needs_input"
    app.button(key="m2_load_example").click().run()
    assert not app.exception
    app.button(key="m2_generate").click().run()
    assert not app.exception
    original = app.session_state["m2_session"].profile.model_copy(deep=True)
    app.chat_input(key="m2_chat").set_value("Change my tuition budget to 50000").run()
    assert not app.exception
    session = app.session_state["m2_session"]
    assert session.profile.tuition_budget_usd == 50000
    assert session.profile.gpa == original.gpa and session.profile.english == original.english
    assert not session.usage and session.current_result["model_status"] == "not_configured"
    assert app.text_input(key="m2_input_budget").value == "50000"
    message_count = len(session.messages)
    app.run()
    assert not app.exception and len(app.session_state["m2_session"].messages) == message_count
    # Saving a goal change must preserve exact cents and the existing English score.
    app.text_input(key="m2_input_budget").set_value("50000.25")
    app.selectbox(key="m2_input_goal").set_value("research")
    app.button(key="m2_save_profile").click().run()
    assert not app.exception
    saved = app.session_state["m2_session"].profile
    assert saved.tuition_budget_usd == Decimal("50000.25") and saved.goal == "research"
    assert saved.gpa == original.gpa and saved.english == original.english
    for kind in ["markdown", "caption", "warning", "info", "subheader", "button", "checkbox", "selectbox", "number_input", "text_input", "text_area"]:
        for element in app.get(kind):
            for attribute in ["value", "label", "options", "help"]:
                assert not re.search(r"[\u3400-\u9fff]", str(getattr(element, attribute, None)))
    old_id = session.session_id
    app.button(key="m2_reset").click().run()
    assert not app.exception
    assert app.session_state["m2_session"].session_id != old_id
    assert not app.session_state["m2_session"].messages
    assert app.session_state["m2_session"].profile.tuition_budget_usd is None
    assert hashlib.sha256(database.read_bytes()).hexdigest() == before_hash
