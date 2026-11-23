"""Check the four-program official evidence update and calculation scopes."""

from datetime import date

import pytest

from gradmatch.catalog import load_seed
from gradmatch.constraints import check_constraints, evidence_ids
from gradmatch.directory import build_directory
from gradmatch.schemas import GPA
from gradmatch.session import tiering_profile
from gradmatch.storage import PROJECT_ROOT


UW = "uw-ece-msece-pmp-seattle"
NYU = "nyu-mscs-tandon-brooklyn"
ILLINOIS = "uiuc-mcs-urbana"
USC = "usc-mscs-general-los-angeles"
AS_OF = date(2026, 11, 22)


@pytest.fixture(scope="module")
def batch():
    return load_seed(PROJECT_ROOT / "data/catalog/dp_batch_review_seed.json")


def assess(batch, program_id, *, scope="overall", value="3.8", as_of=AS_OF):
    programs, sources = batch
    program = next(p for p in programs if p.program_id == program_id)
    profile = tiering_profile().model_copy(update={"gpa": GPA(value=value, scale=4, scope=scope)})
    assessment = check_constraints(profile, program, sources, as_of=as_of)
    return assessment, {check.rule_id: check for check in assessment.checks}


def test_batch_updates_four_exact_programs_and_preserves_existing_evidence(batch):
    programs, sources = batch
    old, earlier_sources = load_seed(PROJECT_ROOT / "data/catalog/cs75_planning_seed.json")
    assert {before.program_id for before, after in zip(old, programs, strict=True) if before != after} == {
        UW, NYU, ILLINOIS, USC,
    }
    assert {key: sources[key] for key in earlier_sources} == earlier_sources
    new_sources = [sources[key] for key in sources.keys() - earlier_sources.keys()]
    assert len(new_sources) == 10
    assert {source.program_id for source in new_sources} == {UW, NYU, ILLINOIS, USC}
    assert build_directory(programs, sources)["total"] == 83


def test_uiuc_last_two_years_is_an_independent_calculation_scope(batch):
    _, overall = assess(batch, ILLINOIS)
    _, last_60 = assess(batch, ILLINOIS, scope="last_60_semester")
    report, matches = assess(batch, ILLINOIS, scope="last_two_years", value="3.1")
    _, exceptional = assess(batch, ILLINOIS, scope="last_two_years", value="2.9")
    assert overall["gpa"].reason_code == last_60["gpa"].reason_code == "GPA_SCOPE_MISMATCH"
    assert matches["gpa"].reason_code == "GPA_MEETS_MINIMUM"
    assert exceptional["gpa"].reason_code == "GPA_EXCEPTION_REQUIRES_REVIEW"
    assert matches["deadline"].reason_code == "DEADLINE_NOT_VERIFIED"
    assert report.tuition.upper_usd is None


def test_usc_fall_2027_dates_and_placement_policy(batch):
    _, active = assess(batch, USC)
    _, after_priority = assess(batch, USC, as_of=date(2026, 12, 16))
    _, late = assess(batch, USC, as_of=date(2027, 1, 16))
    assert active["intake"].status == "pass"
    assert active["gpa"].reason_code == "NO_HARD_GPA_MINIMUM"
    assert active["english"].status == "unknown" and active["english"].source_ids
    assert active["deadline"].status == after_priority["deadline"].status == "pass"
    assert late["deadline"].reason_code == "FINAL_DEADLINE_NOT_VERIFIED"


def test_uw_and_nyu_goals_require_official_program_bindings(batch):
    programs, sources = batch
    by_id = {program.program_id: program for program in programs}
    for program_id, expected in ((UW, {"employment"}), (NYU, {"employment", "research"})):
        program = by_id[program_id]
        bound = evidence_ids(program, "goal_features", sources, tiering_profile())
        assert {feature.goal for feature in program.goal_features} == expected
        assert all(set(feature.source_ids) <= set(bound) and feature.source_ids for feature in program.goal_features)
    _, uw_overall = assess(batch, UW)
    ready, uw_scope = assess(batch, UW, scope="last_90_quarter")
    _, nyu = assess(batch, NYU)
    assert uw_overall["gpa"].reason_code == "GPA_SCOPE_MISMATCH"
    assert ready.recommendation_ready and uw_scope["gpa"].status == "pass"
    assert nyu["gpa"].reason_code == "GPA_SCOPE_NOT_VERIFIED"
