"""Exercise the history ranking path with a controlled provider and no network."""

from datetime import date
import json

import pytest

from gradmatch.admission_history import HistoryPreview
from gradmatch.catalog import load_seed
from gradmatch.config import ModelSettings
from gradmatch.ranking import PreliminaryRecommendationDraft
from gradmatch.schemas import GPA, Intake
from gradmatch.service import start_task
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import PROJECT_ROOT
from scripts.verify_broad_recommendations import BroadFixture


USC = "usc-mscs-general-los-angeles"
UCSD = "ucsd-ms-cs-la-jolla"
ILLINOIS = "uiuc-mcs-urbana"
UCI_MCS = "uci-mcs-irvine"
STANFORD = "community-sss-stanford-mscs"
AS_OF = date(2026, 11, 22)


class HistoryFixture(BroadFixture):
    """Select USC using an offered ID, or use the existing context-free fixture."""

    def __init__(self, *, foreign_reference=False):
        super().__init__()
        self.foreign_reference = foreign_reference

    def generate(self, kind, purpose, payload, session):
        draft = super().generate(kind, purpose, payload, session)
        if purpose != "rank":
            return draft
        options = {row["program_id"]: row["evidence_id"] for row in payload.get("admission_history_options", [])}
        if USC in options:
            reference_id = options[UCSD if self.foreign_reference else USC]
            draft.suggestions.insert(0, PreliminaryRecommendationDraft(
                program_id=USC, reason_check_ids=["application_info"], history_evidence_id=reference_id,
            ))
            draft.suggestions = draft.suggestions[:8]
        return draft

    def rank_inputs(self):
        return [payload for purpose, payload in self.calls if purpose == "rank"]


@pytest.fixture(scope="module")
def catalog():
    return load_seed(PROJECT_ROOT / "data/catalog/dp_batch_review_seed.json")


@pytest.fixture(scope="module")
def history():
    counts = {
        USC: {"admitted": 9, "rejected": 0, "assumed_overall": 9},
        UCSD: {"admitted": 15, "rejected": 4, "assumed_overall": 19},
        ILLINOIS: {"admitted": 2, "rejected": 2, "assumed_overall": 4},
        "unknown-program": {"admitted": 50, "rejected": 0, "assumed_overall": 50},
    }
    return HistoryPreview(
        intake=Intake(year=2027, term="fall"), cycles=[2024, 2025, 2026],
        snapshot_date=date(2026, 10, 25), gpa_scale=4, gpa_scope="overall",
        programs=counts, gpa_bands={pid: {15: row} for pid, row in counts.items()},
    )


def run(catalog, session, provider, *, history=None, strategy="fixed", request_id="first", **kwargs):
    programs, sources = catalog
    limits = json.loads((PROJECT_ROOT / "config/app.json").read_text(encoding="utf-8"))
    settings = ModelSettings("fixture", "offline-fixture", False, "", limits)
    return start_task(
        session, request_id=request_id, programs=programs, sources=sources,
        settings=settings, as_of=AS_OF, provider=provider,
        strategy=strategy, recommendation_scope="broad", history_preview=history, **kwargs,
    )


def new_session():
    profile = tiering_profile().model_copy(update={"gpa": GPA(value="3.80", scale=4)})
    return Session(profile=profile)


@pytest.mark.parametrize("strategy", ["fixed", "react", "plan"])
def test_history_ab_reaches_each_shared_rank_tool_and_preserves_formal_tiers(catalog, history, strategy):
    without_provider, with_provider = HistoryFixture(), HistoryFixture()
    without = run(catalog, new_session(), without_provider, strategy=strategy)
    session = new_session()
    with_history = run(catalog, session, with_provider, history=history, strategy=strategy)

    assert without["validation_passed"] and with_history["validation_passed"]
    assert without["recommendations"] == with_history["recommendations"]
    assert without["excluded"] == with_history["excluded"]
    assert without["preliminary_recommendations"][0]["program_id"] == STANFORD
    assert "admission_history_options" not in without_provider.rank_inputs()[0]
    for purpose, payload in with_provider.calls:
        if purpose != "rank":
            assert "admission_history_options" not in payload
    assert len(with_provider.rank_inputs()) == len(without_provider.rank_inputs()) == 1
    rank_input = with_provider.rank_inputs()[0]
    assert UCI_MCS in rank_input["allowed_preliminary_program_ids"]
    assert UCI_MCS not in rank_input["allowed_recommendation_program_ids"]
    assert UCI_MCS not in {option["program_id"] for option in rank_input["ready_recommendation_options"]}
    assert "cmu-msaii-pittsburgh" in rank_input["allowed_recommendation_program_ids"]
    options = rank_input["admission_history_options"]
    assert {item["program_id"] for item in options} == {USC, UCSD}
    usc_options = next(item for item in options if item["program_id"] == USC)
    assert set(usc_options) == {
        "evidence_id", "program_id", "basis", "source", "snapshot_date", "admission_cycles", "intake",
        "gpa_scale", "gpa_scope", "gpa_band", "admitted", "rejected", "assumed_overall",
    }
    suggestion = with_history["preliminary_recommendations"][0]
    assert suggestion["program_id"] == USC and suggestion["personalized_tier"] is None
    assert suggestion["admission_history_evidence"] == usc_options
    assert with_history["admission_history_ranking"]["referenced_suggestions"] == 1
    assert not any(usage.get("actual_request") for usage in session.usage)


def test_followup_budget_blocks_a_program_with_history(catalog, history):
    provider, session = HistoryFixture(), new_session()
    first = run(catalog, session, provider, history=history, strategy="plan")
    second = run(catalog, session, provider, history=history, strategy="plan", request_id="budget",
                 message="Change my tuition budget to 50000.")
    assert second["task_id"] == first["task_id"]
    assert second["validation_passed"]
    assert USC in {item["program_id"] for item in second["excluded"]}
    assert USC not in {item["program_id"] for item in second["preliminary_recommendations"]}
    assert USC not in {item["program_id"] for item in provider.rank_inputs()[-1].get("admission_history_options", [])}


def test_employment_only_goal_evidence_does_not_authorize_formal_research_tier(catalog, history):
    session, provider = new_session(), HistoryFixture()
    session.profile = session.profile.model_copy(update={"goal": "research"})
    result = run(catalog, session, provider, strategy="plan", history=history)
    rank_input = provider.rank_inputs()[0]
    assert result["validation_passed"]
    assert "cmu-msaii-pittsburgh" in rank_input["allowed_preliminary_program_ids"]
    assert "cmu-msaii-pittsburgh" not in rank_input["allowed_recommendation_program_ids"]


@pytest.mark.parametrize("strategy", ["fixed", "react", "plan"])
def test_research_shortlist_prioritizes_verified_paths_and_rechecks_budget(catalog, history, strategy):
    class ResearchFixture(HistoryFixture):
        def generate(self, kind, purpose, payload, session):
            draft = super().generate(kind, purpose, payload, session)
            if purpose == "act" and draft.tool in {"check_constraints", "rank_programs"}:
                assert payload["tools"][draft.tool]["properties"]["program_ids"]["minItems"] == 0
                arguments = json.loads(draft.arguments_json)
                arguments["program_ids"] = []
                return draft.model_copy(update={"arguments_json": json.dumps(arguments)})
            return draft

    session, provider = new_session(), ResearchFixture()
    session.profile = session.profile.model_copy(update={"goal": "research"})
    first = run(catalog, session, provider, strategy=strategy, history=history)
    lowered = run(catalog, session, provider, strategy=strategy, history=history, request_id="lowered",
                  message="Change my tuition budget to 50000.")

    nyu = "nyu-mscs-tandon-brooklyn"
    illinois_thesis = "community-ss-uiuc-mscs"
    for result in (first, lowered):
        assert result["validation_passed"] and len(result["retrieved_program_ids"]) == 83
        shortlist = result["preliminary_recommendations"]
        assert len({item["program_id"] for item in shortlist}) == len(shortlist)
        for item in shortlist[:5]:
            assert item["personalized_tier"] is None
            assert item["research_fit"]["program_source"].startswith("https://")
            assert item["research_fit"]["research_source"].startswith("https://")
        assert len(shortlist) >= 5
        assert ILLINOIS not in {item["program_id"] for item in shortlist[:5]}
    initial_options, updated_options = ({row["program_id"] for row in payload["research_path_options"]}
                                        for payload in provider.rank_inputs())
    assert nyu in initial_options and nyu not in updated_options
    assert illinois_thesis in updated_options and ILLINOIS not in updated_options
    assert nyu in {item["program_id"] for item in lowered["excluded"]}
    assert illinois_thesis in {item["program_id"] for item in lowered["preliminary_recommendations"][:5]}
    if strategy == "react":
        checks = [entry for entry in lowered["task_usage"]["tool_log"] if entry["tool"] == "check_constraints"]
        assert checks[-1]["arguments"]["program_ids"] == []
        assert len(checks[-1]["result"]["data"]["reports"]) == 83


def test_cross_program_reference_is_rejected(catalog, history):
    result = run(catalog, new_session(), HistoryFixture(foreign_reference=True), history=history)
    assert not result["validation_passed"]
    assert USC not in {item["program_id"] for item in result["preliminary_recommendations"]}
    assert any("UNSUPPORTED_ADMISSION_HISTORY_REFERENCE" in item.get("codes", [])
               for item in result["validation_errors"])


def test_profile_scope_and_toggle_cannot_reuse_history(catalog, history):
    session, provider = new_session(), HistoryFixture()
    initial = run(catalog, session, provider, history=history, strategy="plan")
    mismatched = run(
        catalog, session, provider, history=history, strategy="plan", request_id="scope",
        changes={"gpa": {"value": "3.80", "scale": "4", "scope": "last_90_quarter"}},
    )
    assert initial["task_id"] == mismatched["task_id"]
    assert mismatched["admission_history_ranking"]["offered_options"] == 0
    assert "admission_history_options" not in provider.rank_inputs()[-1]

    off = run(catalog, session, provider, strategy="plan", request_id="off")
    assert off["task_id"] != mismatched["task_id"]
    assert not off["admission_history_ranking"]["enabled"]
