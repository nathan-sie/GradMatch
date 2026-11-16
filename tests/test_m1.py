"""M1: numerical, evidence, intake and session-independent rule boundaries."""

from contextlib import closing
from datetime import date, datetime, timezone
from decimal import Decimal
import json
import re
from pathlib import Path
import sqlite3

import pytest
from pydantic import ValidationError
from streamlit.testing.v1 import AppTest

from gradmatch.catalog import DEFAULT_SEED, coverage_rows, import_catalog, load_seed, read_catalog
from gradmatch.constraints import check_constraints, estimate_tuition
from gradmatch.schemas import (
    ApplicantProfile, EnglishScore, GPA, GPARequirement, Intake, ProgramRecord,
    SourceRecord, TuitionPolicy,
)
from gradmatch.storage import PROJECT_ROOT, inspect_catalog


AS_OF = date(2026, 11, 13)


def profile(**changes):
    data = dict(gpa={"value": "3.5", "scale": "4", "scope": "last_60_semester"},
        english_status="known", english={"version": "toefl_120", "total": "100", "test_date": "2025-11-01"},
        intake={"year": 2027, "term": "fall"}, tuition_budget_usd="50000",
        coursework=dict.fromkeys(["calculus", "differential_equations", "linear_algebra", "programming", "data_structures", "algorithms", "probability_statistics"], True))
    data.update(changes)
    return ApplicantProfile.model_validate(data)


def fixture_catalog(**changes):
    data = dict(program_id="fixture-mcs", university="Fixture University", school="Fixture CS",
        program_name="Fixture MCS", degree="MCS", campus="Fixture", track="Fixture",
        discipline="CS", official_url="https://fixture.example.edu/mcs", allowed_official_hosts=["fixture.example.edu"],
        candidate_source_id="fixture", required_credits="32", catalog_version="test-only",
        gpa={"minimum": "3", "scale": "4", "accepted_scopes": ["last_60_semester"]},
        english=[{"version": "ielts_9", "minimum_total": "7", "minimum_subscores": {"speaking": "6"}, "validity_years": 2}],
        required_topics=["programming"], prerequisites_complete=True,
        supported_intakes=[{"year": 2027, "term": "fall"}],
        deadlines=[{"intake": {"year": 2027, "term": "fall"}, "date": "2027-01-15", "label": "Final"}],
        deadline_schedule_complete=True,
        tuition={"basis": "per_credit", "unit_rate_lower": "1500", "required_units_lower": "32", "rate_year": "2026-2027"})
    data.update(changes)
    program = ProgramRecord.model_validate(data)
    groups = ["identity", "credits", "gpa", "english", "prerequisites", "tuition", "intake", "deadline"]
    bindings = {group: {"program_id": program.program_id} for group in groups}
    bindings["tuition"].update({"tuition.unit_rate_lower": program.model_dump(mode="json")["tuition"]["unit_rate_lower"]})
    source = SourceRecord(source_id="fixture-source", program_id=program.program_id,
        url="https://fixture.example.edu/mcs", title="Synthetic fixture, not a real school",
        source_type="official_program", retrieved_at=datetime(2026, 11, 13, tzinfo=timezone.utc),
        field_groups=groups, verified_values=bindings, source_excerpt="Synthetic test fixture.",
        fact_summary="Synthetic fixture only.", locator="fixture", snapshot_path="fixture.json",
        content_hash="0" * 64, raw_response_sha256="0" * 64)
    program.field_sources = dict.fromkeys(groups, [source.source_id])
    return program, {source.source_id: source}


def rule(profile_, program, sources, key, as_of=AS_OF):
    return next(check for check in check_constraints(profile_, program, sources, as_of=as_of).checks if check.rule_id == key)


@pytest.mark.parametrize("budget,expected", [("50000", "pass"), ("47000", "fail"), ("48000", "pass"), ("0", "fail")])
def test_full_program_budget_uses_all_credits(budget, expected):
    program, sources = fixture_catalog()
    assert estimate_tuition(program.tuition).upper_usd == Decimal("48000")
    assert rule(profile(tuition_budget_usd=budget), program, sources, "tuition").status == expected


@pytest.mark.parametrize("basis", ["per_credit", "per_term", "per_year"])
def test_missing_billable_units_never_uses_unit_rate_as_total(basis):
    result = estimate_tuition(TuitionPolicy(basis=basis, unit_rate_lower="1500", rate_year="2026-2027"))
    assert result.upper_usd is None and result.reason_code == "MISSING_TOTAL_UNITS"


def test_tuition_interval_crossing_budget_is_not_accepted():
    program, sources = fixture_catalog(tuition={"basis": "per_credit", "unit_rate_lower": "1450", "unit_rate_upper": "1600", "required_units_lower": "32", "rate_year": "2026-2027"})
    assert rule(profile(), program, sources, "tuition").status == "fail"


def test_rounding_cannot_hide_budget_violation():
    program, sources = fixture_catalog(tuition={"basis": "per_credit", "unit_rate_lower": "1500.00001", "required_units_lower": "32", "rate_year": "2026-2027"})
    assert rule(profile(tuition_budget_usd="48000"), program, sources, "tuition").status == "fail"


def test_no_currency_conversion_or_final_price_guarantee():
    assert estimate_tuition(TuitionPolicy(currency="EUR", basis="full_program", unit_rate_lower="1000", rate_year="2026-2027")).upper_usd is None
    program, sources = fixture_catalog()
    assert rule(profile(budget_basis="guaranteed_final"), program, sources, "tuition").reason_code == "FINAL_TUITION_NOT_GUARANTEED"


@pytest.mark.parametrize("gpa,code", [
    ({"value": "85", "scale": "100", "scope": "last_60_semester"}, "GPA_SCALE_MISMATCH"),
    ({"value": "3.5", "scale": "4", "scope": "overall"}, "GPA_SCOPE_MISMATCH"),
    ({"value": "2.9", "scale": "4", "scope": "last_60_semester"}, "GPA_BELOW_MINIMUM"),
])
def test_gpa_scale_scope_and_boundary(gpa, code):
    program, sources = fixture_catalog()
    assert rule(profile(gpa=gpa), program, sources, "gpa").reason_code == code


def test_recommended_gpa_and_exception_are_not_automatic_rejections():
    program, sources = fixture_catalog(gpa={"recommended": "3.2"})
    assert rule(profile(), program, sources, "gpa").status == "unknown"
    program, sources = fixture_catalog(gpa={"minimum": "3", "accepted_scopes": ["last_60_semester"], "below_minimum_review_possible": True})
    assert rule(profile(gpa={"value": "2.9", "scale": "4", "scope": "last_60_semester"}), program, sources, "gpa").status == "unknown"


@pytest.mark.parametrize("english,expected", [
    ({"version": "ielts_9", "total": "7", "test_date": "2025-11-01"}, "unknown"),
    ({"version": "ielts_9", "total": "7", "subscores": {"speaking": "5.5"}, "test_date": "2025-11-01"}, "fail"),
    ({"version": "ielts_9", "total": "7", "subscores": {"speaking": "6"}}, "unknown"),
    ({"version": "ielts_9", "total": "7", "subscores": {"speaking": "6"}, "test_date": "2024-11-13"}, "fail"),
    ({"version": "ielts_9", "total": "7", "subscores": {"speaking": "6"}, "test_date": "2025-11-01"}, "pass"),
])
def test_english_total_subscores_date_and_expiry(english, expected):
    program, sources = fixture_catalog()
    assert rule(profile(english=english), program, sources, "english").status == expected


def test_real_uw_minimum_does_not_erase_additional_english_conditions():
    programs, sources = load_seed()
    uw = next(item for item in programs if item.program_id.startswith("uw-"))
    result = rule(profile(english={"version": "toefl_120", "total": "85", "test_date": "2025-11-01"}), uw, sources, "english")
    assert result.status == "pass" and result.warnings
    result = rule(profile(english={"version": "toefl_120", "total": "100", "test_date": "2026-03-01"}), uw, sources, "english")
    assert result.reason_code == "TOEFL_VERSION_DATE_MISMATCH"


def test_unknown_and_absent_coursework_are_different():
    program, sources = fixture_catalog()
    assert rule(profile(coursework={}), program, sources, "prerequisites").status == "unknown"
    assert rule(profile(coursework={"programming": False}), program, sources, "prerequisites").status == "fail"
    program, sources = fixture_catalog(required_topics=[], prerequisites_complete=True)
    assert rule(profile(), program, sources, "prerequisites").status == "not_applicable"


def test_deadline_today_and_after_all_rounds():
    program, sources = fixture_catalog()
    assert rule(profile(), program, sources, "deadline", date(2027, 1, 15)).status == "unknown"
    assert rule(profile(), program, sources, "deadline", date(2027, 1, 16)).status == "fail"


def test_real_uw_part_time_round_is_not_an_international_full_time_extension():
    programs, sources = load_seed()
    uw = next(item for item in programs if item.program_id.startswith("uw-"))
    assert rule(profile(), uw, sources, "deadline", date(2027, 2, 1)).status == "pass"
    assert rule(profile(), uw, sources, "deadline", date(2027, 3, 6)).status == "fail"


def test_wrong_intake_and_conflicting_evidence_do_not_pass():
    program, sources = fixture_catalog()
    assert rule(profile(intake={"year": 2028, "term": "fall"}), program, sources, "intake").status == "unknown"
    sources["fixture-source"].verification_status = "conflict"
    assert rule(profile(), program, sources, "tuition").status == "unknown"


def test_editing_a_rate_without_evidence_invalidates_the_calculation():
    program, sources = fixture_catalog()
    program.tuition.unit_rate_lower = Decimal("1")
    assert rule(profile(), program, sources, "tuition").reason_code == "MISSING_TUITION_EVIDENCE"


@pytest.mark.parametrize("payload", [{"value": "4.1", "scale": "4"}, {"value": "3", "scale": "0"}, {"value": "NaN", "scale": "4"}])
def test_invalid_gpa_is_rejected(payload):
    with pytest.raises(ValidationError):
        GPA.model_validate(payload)


def test_english_version_range_and_negative_budget_are_rejected():
    with pytest.raises(ValidationError): EnglishScore(version="toefl_6", total="100")
    with pytest.raises(ValidationError): profile(tuition_budget_usd="-1")


def test_seed_has_eight_distinct_programs_and_real_official_provenance():
    programs, sources = load_seed()
    assert len(programs) == 8 and len(sources) == 20
    assert len({item.program_id for item in programs}) == 8
    assert all(source.url.host.endswith(".edu") for source in sources.values())
    assert all(len(source.source_excerpt.split()) <= 25 for source in sources.values())
    coverage = coverage_rows(programs, sources)
    assert sum(row["tuition_estimate_usd"] is not None for row in coverage) == 3
    assert all(row["recommendation_ready"] is False for row in coverage)


def test_import_is_repeatable_and_wrong_evidence_does_not_write(tmp_path):
    database = tmp_path / "catalog.db"
    import_catalog(database=database)
    import_catalog(database=database)
    assert inspect_catalog(database).program_count == 8
    assert inspect_catalog(database).source_count == 20
    document = json.loads(DEFAULT_SEED.read_text(encoding="utf-8"))
    document["programs"][0]["tuition"]["unit_rate_lower"] = "1"
    invalid = tmp_path / "invalid_seed.json"
    invalid.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="do not match evidence"):
        import_catalog(invalid, tmp_path / "should_not_exist.db")
    assert not (tmp_path / "should_not_exist.db").exists()


def test_budget_update_preserves_inputs_and_does_not_reuse_previous_checks():
    programs, sources = load_seed()
    uw = next(item for item in programs if item.program_id.startswith("uw-"))
    previous = profile(tuition_budget_usd="70000")
    updated = ApplicantProfile.model_validate({**previous.model_dump(), "tuition_budget_usd": "50000", "profile_version": 2})
    assert updated.gpa == previous.gpa and updated.english == previous.english
    assert updated.goal == previous.goal and updated.intake == previous.intake
    before = check_constraints(previous, uw, sources, as_of=AS_OF)
    after = check_constraints(updated, uw, sources, as_of=AS_OF)
    assert next(check for check in before.checks if check.rule_id == "tuition").status == "pass"
    assert next(check for check in after.checks if check.rule_id == "tuition").status == "fail"
    assert before.profile_version == 1 and after.profile_version == 2
    assert before.recommendation_ready is False and after.recommendation_ready is False


def test_m1_page_checks_and_budget_update(tmp_path, monkeypatch):
    database = tmp_path / "catalog.db"
    import_catalog(database=database)
    monkeypatch.setenv("GRADMATCH_DB_PATH", str(database))
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=15).run()
    assert not app.exception
    app.radio(key="workspace_page").set_value("Data and rule checks (M1)").run()
    app.button(key="run_m1").click().run()
    assert not app.exception
    before = app.session_state["m1_result"]
    uw_before = next(report for report in before["reports"] if report["program_id"].startswith("uw-"))
    assert next(check for check in uw_before["checks"] if check["rule_id"] == "tuition")["status"] == "pass"
    app.number_input(key="m1_budget").set_value(50000)
    app.button(key="run_m1").click().run()
    assert not app.exception
    after = app.session_state["m1_result"]
    uw_after = next(report for report in after["reports"] if report["program_id"].startswith("uw-"))
    assert next(check for check in uw_after["checks"] if check["rule_id"] == "tuition")["status"] == "fail"
    assert after["profile"]["gpa"] == before["profile"]["gpa"]
    assert after["profile"]["english"] == before["profile"]["english"]
    assert not re.search(r"[\u3400-\u9fff]", json.dumps(after, ensure_ascii=False))
    # Check rendered labels, results and evidence annotations for every program,
    # including content inside expanders rather than only the page heading.
    for program in read_catalog(database)[0]:
        app.selectbox(key="m1_selected_program").set_value(program.program_id).run()
        assert not app.exception
        for kind in ["markdown", "caption", "info", "warning", "error", "subheader", "code",
                     "expander", "button", "selectbox", "number_input", "checkbox", "multiselect", "date_input"]:
            for element in app.get(kind):
                for attribute in ["value", "label", "options", "help"]:
                    value = getattr(element, attribute, None)
                    assert not re.search(r"[\u3400-\u9fff]", str(value)), (kind, attribute, value)
