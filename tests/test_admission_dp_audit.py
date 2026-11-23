"""Check identity, recency, deduplication, and GPA coverage without real applicant data."""

from copy import deepcopy
from datetime import datetime
from decimal import Decimal
import json

import pytest
from streamlit.testing.v1 import AppTest

from gradmatch import admission_history
from gradmatch.bootstrap import bootstrap_public_catalog
from gradmatch.catalog import load_seed
from gradmatch.providers import OpenAIProvider
from gradmatch.schemas import GPA, Intake
from gradmatch.session import tiering_profile
from gradmatch.storage import PROJECT_ROOT
from scripts.audit_admission_dp import SEED, audit, load_mappings
from scripts.audit_target_readiness import review_profiles


@pytest.fixture(scope="module")
def manifest():
    return load_mappings()


def record(person="fixture-owner", *, year=2026, term="Fall", outcome="Admit", scale="4.0", scope=None):
    applicant = {
        "id": person, "gpa": "3.5", "gpa_scale": scale,
        "contact_info": "private fixture contact", "gpa_notes": "private fixture note",
    }
    if scope is not None:
        applicant["gpa_scope"] = scope
    return {
        "p": {"id": "aplus-ucsd-cs75", "school": "UCSD", "program": "CS75", "degree": "Master"},
        "d": {"applicant_id": person, "program_id": "aplus-ucsd-cs75",
              "academic_year": year, "semester": term, "result": outcome},
        "a": applicant,
    }


def export(records):
    return {
        "complete": True, "saved_records": len(records), "reported_total_at_start": len(records),
        "downloaded_at_utc": "2026-10-25T18:08:15+00:00", "records": list(records),
    }


def run(manifest, *records, scope="overall"):
    return audit(export(records), manifest, intake=Intake(year=2027, term="fall"),
                 comparison=GPA(value=0, scale=4, scope=scope))


def test_manifest_binds_reviewed_and_preliminary_recommendation_identities(manifest):
    assert {mapping["program_id"] for mapping in manifest["programs"]} == {
        "ucsd-ms-cs-la-jolla", "usc-mscs-general-los-angeles", "uiuc-mcs-urbana",
        "uw-ece-msece-pmp-seattle", "nyu-mscs-tandon-brooklyn",
        "cmu-msaii-pittsburgh", "uiuc-meng-ece-urbana", "uci-mcs-irvine", "gatech-mscs-atlanta",
        "community-a-minus-brown-scmcs", "community-ss-cmu-mscs",
        "community-b-plus-nwu-mscs", "community-ss-uiuc-mscs",
    }


def brown_record(person, *, year):
    result = record(person, year=year)
    source_id = "pgm_0mpc5vdqw00009a0bb2kdo9n5d"
    result["p"].update(id=source_id, school="Brown", program="ScM CS")
    result["d"]["program_id"] = source_id
    return result


def test_brown_mapping_respects_the_pre_online_cohort_boundary(manifest):
    source = export([brown_record("earlier", year=2026), brown_record("unspecified-route", year=2027)])
    source["downloaded_at_utc"] = "2027-10-25T18:08:15+00:00"
    report = audit(source, manifest, intake=Intake(year=2028, term="fall"), comparison=GPA(value=0, scale=4))
    row = next(row for row in report["programs"] if row["program_id"] == "community-a-minus-brown-scmcs")
    assert row["outcomes"] == {"reported_admit": 1}
    assert row["rejected_route_rows"] == 1


def test_preliminary_history_does_not_claim_official_eligibility(manifest):
    first = brown_record("first", year=2025)
    second = brown_record("second", year=2026)
    for row in (first, second):
        row["a"].update(ug_major="CS", research_domestic_count=1)
    report = review_profiles(export([first, second]), manifest, *load_seed(SEED), ["3.50"],
                             datetime(2026, 11, 21).date())
    row = next(row for row in report["scenarios"][0]["programs"] if row["program_id"] == "community-a-minus-brown-scmcs")
    assert row["reported_background_matches"] == {"admitted": 2, "rejected": 0}
    assert not row["official_eligibility_passed"] and not row["target_supported"]
    assert row["official_blockers"][0]["reason"] == "MISSING_OFFICIAL_PROGRAM_RECORD"


def test_recent_exact_scoped_identity(manifest):
    near_match = record("different-track")
    near_match["p"]["program"] = "CS76"
    ambiguous_id = record("ambiguous-id")
    ambiguous_id["d"]["program_id"] = "b-usc-cs28"
    wrong_degree = record("doctoral")
    wrong_degree["p"]["degree"] = "PhD"
    report = run(manifest, record("recent"), near_match, ambiguous_id, wrong_degree,
                 record("old", year=2023), record("spring", term="Spring"), record("future", year=2027))
    row = report["programs"][0]
    assert report["report_cycles"] == [2024, 2025, 2026]
    assert row["source_reports_all_cycles"] == 4
    assert row["source_reports_in_window"] == 1
    assert row["rejected_identity_rows"] == 3
    assert report["programs"][1]["rejected_identity_rows"] == 1


def test_duplicate_and_conflicting_reports_are_not_additional_evidence(manifest):
    same_report = record(scope="overall")
    report = run(manifest, same_report, deepcopy(same_report),
                 record("repeat", year=2024, scope="overall"),
                 record("repeat", outcome="Reject", scope="overall"),
                 record("conflict"), record("conflict", outcome="Withdraw"))
    row = report["programs"][0]
    assert row["source_reports_in_window"] == 6
    assert row["distinct_applicants_in_window"] == 3
    assert row["duplicate_reports_in_window"] == 2
    assert row["earlier_cycles_for_repeat_applicants"] == 1
    assert row["conflicting_applicant_cycles"] == 1
    assert row["outcomes"] == {"conflicting_reports": 1, "reported_admit": 1, "reported_reject": 1}
    assert row["same_gpa_scale_and_scope_outcomes"] == {"reported_admit": 1, "reported_reject": 1}
    assert row["same_scale_and_scope_admit_count"] == 1


def test_missing_scope_is_counted_as_assumed_overall(manifest):
    report = run(manifest, record(), record("known", scope="overall"),
                 record("no-decision", outcome="\u9ed8\u62d2", scope="overall"),
                 record("quarter", scope="last_90_quarter"),
                 record("unrecognized", scope="unknown"),
                 record("other-scale", scale="4.3", scope="overall"))
    row = report["programs"][0]
    assert row["same_gpa_scale_outcomes"] == {"no_explicit_decision": 1, "reported_admit": 4}
    assert row["same_gpa_scale_unknown_scope_outcomes"] == {"reported_admit": 2}
    assert row["same_gpa_scale_and_scope_outcomes"] == {"no_explicit_decision": 1, "reported_admit": 1}
    assert row["same_gpa_scale_assumed_overall_outcomes"] == {"reported_admit": 1}
    assert row["same_gpa_scale_and_effective_scope_outcomes"] == {"no_explicit_decision": 1, "reported_admit": 2}
    serialized = json.dumps(report)
    assert "fixture-owner" not in serialized
    assert "private fixture" not in serialized


def test_overall_assumption_does_not_match_a_quarter_credit_gpa(manifest):
    report = run(manifest, record(), record("quarter", scope="last_90_quarter"),
                 scope="last_90_quarter")
    row = report["programs"][0]
    assert row["same_gpa_scale_assumed_overall_outcomes"] == {}
    assert row["same_gpa_scale_and_effective_scope_outcomes"] == {"reported_admit": 1}


def test_incomplete_export_is_rejected(manifest):
    data = {**export([record()]), "saved_records": 2}
    with pytest.raises(ValueError, match="counts disagree"):
        audit(data, manifest, intake=Intake(year=2027, term="fall"), comparison=GPA(value=0, scale=4))


def test_read_preview_requires_matching_profile_and_valid_aggregates(manifest, tmp_path, monkeypatch):
    file = tmp_path / "preview.json"
    monkeypatch.setattr(admission_history, "PREVIEW_FILE", file)
    profile = tiering_profile()
    assert admission_history.read_preview(profile) is None
    admission_history.write_preview(run(manifest, record(), record("rejected", outcome="Reject")), profile.intake)
    preview = admission_history.read_preview(profile)
    assert preview.snapshot.programs["ucsd-ms-cs-la-jolla"].model_dump() == {
        "admitted": 1, "rejected": 1, "assumed_overall": 2,
    }
    assert preview.band_label == "3.5 to below 3.75"
    assert preview.band_counts("ucsd-ms-cs-la-jolla").total == 2
    assert admission_history.read_preview(profile.model_copy(update={"gpa": None})) is None
    assert admission_history.read_preview(profile.model_copy(update={"intake": Intake(year=2028, term="fall")})) is None
    for changed_gpa in (GPA(value=3.5, scale=5), GPA(value=3.5, scale=4, scope="last_90_quarter")):
        assert admission_history.read_preview(profile.model_copy(update={"gpa": changed_gpa})) is None
    payload = json.loads(file.read_bytes())
    payload["programs"]["ucsd-ms-cs-la-jolla"]["assumed_overall"] = 3
    file.write_text(json.dumps(payload), encoding="utf-8")
    assert admission_history.read_preview(profile) is None


def test_band_boundaries_and_precedence():
    assert [admission_history.gpa_band(Decimal(value), Decimal("4")) for value in ("0", "3.49", "3.5", "3.75", "4")] == [
        0, 13, 14, 15, 15,
    ]
    snapshot = admission_history.HistoryPreview(
        intake=Intake(year=2027, term="fall"), cycles=[2024, 2025, 2026],
        snapshot_date="2026-10-25", gpa_scale=4, gpa_scope="overall", programs={},
        gpa_bands={key: {14: {"admitted": 0, "rejected": count, "assumed_overall": count}}
                   for key, count in {"pending": 8, "a": 5, "b": 5, "blocked": 12, "too_small": 4}.items()},
    )
    comparison = admission_history.HistoryComparison(snapshot, 14)
    result = {
        "preliminary_recommendations": [{"program_id": "a"}, {"program_id": "b"}],
        "pending_verification": [{"program_id": key} for key in ("pending", "blocked", "too_small", "a")],
        "preliminary_excluded": [{"program_id": "blocked"}],
    }
    ordered = [(key, status) for key, status, _ in comparison.covered_candidates(result)]
    assert ordered == [("pending", "Pending verification"), ("a", "Preliminary recommendation"),
                       ("b", "Preliminary recommendation")]


def test_local_history_renders_on_actual_assessment_without_changing_result(manifest, tmp_path, monkeypatch):
    class FrozenClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 11, 21, 12, tzinfo=tz)

    def deny_model(*args, **kwargs):
        raise AssertionError("Applicant history needs no model call.")

    public_cache = tmp_path / "public"
    monkeypatch.setenv("GRADMATCH_DB_PATH", str(bootstrap_public_catalog(public_cache)))
    monkeypatch.setenv("GRADMATCH_PUBLIC_CACHE_DIR", str(public_cache))
    monkeypatch.setenv("MODEL_ENABLED", "false")
    monkeypatch.setattr(OpenAIProvider, "generate", deny_model)
    monkeypatch.setattr(admission_history, "PREVIEW_FILE", tmp_path / "preview.json")
    app = AppTest.from_file(str(PROJECT_ROOT / "app.py"), default_timeout=30).run()
    from gradmatch import ui_m2
    monkeypatch.setattr(ui_m2, "datetime", FrozenClock)
    app.button(key="m35_load_example").click().run()
    app.button(key="m2_generate").click().run()
    assert not app.exception
    session = app.session_state["m2_session"]
    original = deepcopy(session.current_result)
    assert not any("Historical applicant comparisons" in item.value for item in app.markdown)

    report = run(manifest, *(record(f"fixture-{index}", outcome="Reject" if index >= 3 else "Admit")
                             for index in range(5)))
    admission_history.write_preview(report, session.profile.intake)
    app.run()
    assert not app.exception
    assert any("Historical applicant comparisons" in item.value for item in app.markdown)
    assert any("Reported admits (3)" in item.value and "Reported rejects (2)" in item.value for item in app.markdown)
    assert any("Overall GPA was assumed for 5 reports" in item.value for item in app.caption)
    assert any(item.label == "Compare candidates by historical sample coverage" for item in app.expander)
    assert any("GPA band 3.5 to below 3.75" in item.value for item in app.caption)
    assert app.session_state["m2_session"].current_result == original
    assert not app.session_state["m2_session"].usage


def test_target_screen_requires_reported_major_and_experience_and_still_checks_eligibility(manifest):
    first = record("first")
    first["a"].update(ug_major="Computer Science", internship_domestic_count=1)
    second = record("second")
    second["a"].update(ug_major="CS", research_overseas_count=2)
    rejected = record("rejected", outcome="Reject")
    rejected["a"].update(ug_major="computer science", research_domestic_count=1)
    wrong_major = record("wrong-major")
    wrong_major["a"].update(ug_major="Electrical Engineering", internship_domestic_count=1)
    no_experience = record("no-experience")
    no_experience["a"].update(ug_major="CS", research_domestic_count=0, research_overseas_count=None)
    programs, sources = load_seed(SEED)
    report = review_profiles(
        export([first, deepcopy(first), second, rejected, wrong_major, no_experience]),
        manifest, programs, sources, ["3.50", "3.80"], datetime(2026, 11, 21).date(),
    )
    row = report["scenarios"][0]["programs"][0]
    assert row["gpa_band_reports"] == {"admitted": 4, "rejected": 1}
    assert row["reported_background_matches"] == {"admitted": 2, "rejected": 1}
    assert row["background_review_candidates_at_least_two"]
    assert not row["official_eligibility_passed"]
    assert not row["target_supported"]
    assert "INSUFFICIENT_COMPARABLE_CASES" in row["current_tier_validation_errors"]
    assert report["scenarios"][1]["programs"][0]["reported_background_matches"] == {"admitted": 0, "rejected": 0}
