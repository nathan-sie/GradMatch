"""Validate UCSD CS75 evidence and its boundaries in the active catalog."""

from datetime import date
from decimal import Decimal

import pytest

from gradmatch.catalog import DEFAULT_SEED, load_seed
from gradmatch.constraints import check_constraints
from gradmatch.directory import build_directory
from gradmatch.schemas import EnglishScore, GPA
from gradmatch.session import tiering_profile
from gradmatch.storage import PROJECT_ROOT


PROGRAM_ID = "ucsd-ms-cs-la-jolla"
AS_OF = date(2026, 11, 21)


@pytest.fixture(scope="module")
def reviewed_catalog():
    return load_seed(PROJECT_ROOT / "data/catalog/cs75_review_seed.json")


@pytest.fixture(scope="module")
def planning_catalog():
    return load_seed(PROJECT_ROOT / "data/catalog/cs75_planning_seed.json")


def assess(reviewed_catalog, **changes):
    programs, sources = reviewed_catalog
    program = next(item for item in programs if item.program_id == PROGRAM_ID)
    profile = tiering_profile().model_copy(update=changes)
    report = check_constraints(profile, program, sources, as_of=AS_OF)
    return report, {item.rule_id: item for item in report.checks}


def test_only_cs75_and_its_verified_sources_changed(reviewed_catalog):
    programs, sources = reviewed_catalog
    previous, historical_sources = load_seed(DEFAULT_SEED)
    assert [item for item in programs if item.program_id != PROGRAM_ID] == [
        item for item in previous if item.program_id != PROGRAM_ID
    ]
    assert {key: sources[key] for key in historical_sources} == historical_sources
    assert len(sources) - len(historical_sources) == 6
    assert all(sources[key].program_id == PROGRAM_ID for key in sources.keys() - historical_sources.keys())


def test_overall_gpa_toefl_and_cs_preparation_pass(reviewed_catalog):
    report, checks = assess(reviewed_catalog)
    assert all(checks[key].status in {"pass", "not_applicable"} for key in ("gpa", "english", "prerequisites"))
    assert {key for key, check in checks.items() if check.status == "unknown"} == {"tuition", "remaining_eligibility"}
    assert not report.recommendation_ready
    _, different_gpa = assess(reviewed_catalog, gpa=GPA(value="3.8", scale="4", scope="last_90_quarter"))
    assert different_gpa["gpa"].reason_code == "GPA_SCOPE_MISMATCH"


def test_current_score_validity_and_unmodeled_ielts(reviewed_catalog):
    _, stale = assess(reviewed_catalog, english=EnglishScore(version="toefl_120", total=110, test_date=date(2023, 11, 1)))
    assert stale["english"].reason_code == "ENGLISH_EXPIRED"
    _, ielts = assess(reviewed_catalog, english=EnglishScore(version="ielts_9", total=8, test_date=date(2025, 11, 1)))
    assert ielts["english"].status == "unknown"


def test_full_time_minimum_respects_scope_and_does_not_pass_the_budget(reviewed_catalog):
    standard, normal = assess(reviewed_catalog)
    assert standard.tuition.lower_usd == Decimal("13722") and standard.tuition.upper_usd is None
    assert normal["tuition"].reason_code == "MINIMUM_ONLY_TUITION_BOUND"
    assert len(normal["tuition"].source_ids) == 2
    _, below = assess(reviewed_catalog, tuition_budget_usd=Decimal("13721"))
    assert below["tuition"].reason_code == "TUITION_MINIMUM_EXCEEDS_BUDGET"
    part_time, different_schedule = assess(reviewed_catalog, tuition_budget_usd=Decimal("13721"), study_mode="part_time")
    assert part_time.tuition.lower_usd is None and different_schedule["tuition"].status == "unknown"


def test_directory_shows_bound_quarter_rates_and_checklist(reviewed_catalog):
    directory = build_directory(*reviewed_catalog)
    assert directory["total"] == 83
    row = next(item for item in directory["records"] if item["linked_program_id"] == PROGRAM_ID)
    assert row["tuition_lower_usd"] == "13722"
    assert row["tuition_upper_usd"] is None
    assert "recommendations" in row["requirements"]["Application checklist"]


@pytest.mark.parametrize(("prior_degree", "status"), [
    ("none", "pass"), ("held_or_expected", "unknown"), ("unknown", "unknown"),
])
def test_cs75_prior_degree_and_budget_are_independent(planning_catalog, prior_degree, status):
    degree = tiering_profile().degree.model_copy(update={"prior_academic_graduate_degree": prior_degree})
    report, checks = assess(planning_catalog, degree=degree)
    assert checks["remaining_eligibility"].status == status
    if status == "unknown":
        assert checks["remaining_eligibility"].reason_code == "PRIOR_ADVANCED_DEGREE_REQUIRES_REVIEW"
    assert report.tuition.lower_usd == Decimal("13722") and report.tuition.upper_usd is None
    assert checks["tuition"].reason_code == "MINIMUM_ONLY_TUITION_BOUND"
    assert any("27,444" in note and "57,648" in note for note in report.tuition.assumptions)
    assert not report.recommendation_ready


def test_missing_checklist_cannot_pass_remaining_eligibility(planning_catalog):
    programs, sources = planning_catalog
    incomplete = {key: value for key, value in sources.items() if key != f"{PROGRAM_ID}-cse_checklist-cs75-review"}
    _, checks = assess((programs, incomplete))
    assert checks["remaining_eligibility"].reason_code == "ADDITIONAL_ELIGIBILITY_EVIDENCE_INCOMPLETE"
