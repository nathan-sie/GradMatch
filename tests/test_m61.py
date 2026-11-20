"""Audit evidence validity, pricing dependencies and non-promotion of candidates."""

import json
import socket
from copy import deepcopy
from datetime import date

import pytest

from gradmatch.catalog import M35_SEED, load_seed
from gradmatch.catalog_audit import audit_catalog, screen_candidates
from gradmatch.schemas import GPARequirement, Intake
from scripts.audit_catalog import INDEX, LEGACY_REVIEW as REVIEW, build_report

AS_OF = date(2026, 11, 19)
INTAKE = Intake(year=2027, term="fall")


def audited(programs=None, sources=None):
    if programs is None:
        programs, sources = load_seed(M35_SEED)
    return audit_catalog(programs, sources, as_of=AS_OF, intake=INTAKE)


def row(report, pid):
    return next(r for r in report["programs"] if r["program_id"] == pid)


def test_audit_distinguishes_complete_recommendation_from_cohort_evidence_only():
    report = audited()
    summary = report["summary"]
    assert summary["programs"] == 10 and summary["sources"] == 30
    assert summary["computable_verified_tuition"] == 5
    assert (
        summary["reference_hard_checks_ready"]
        == summary["reference_formal_evidence_ready"]
        == 1
    )
    assert (
        summary["reviewed_recent_cohorts"] == 2
        and summary["reviewed_recent_admitted_cases"] == 0
    )
    assert summary["reference_tier_evidence_support"] == {
        "Lottery": 1,
        "Reach": 1,
        "Target": 0,
        "Safer": 0,
    }
    mcds = row(report, "cmu-mcds-pittsburgh")
    assert (
        mcds["reference_supported_tiers"] == ["Reach"]
        and not mcds["reference_formal_evidence_ready"]
    )
    assert mcds["repair_priority"] == 1


def test_applicant_scope_mismatch_is_not_an_official_gpa_data_gap():
    uw = row(audited(), "uw-ece-msece-pmp-seattle")
    assert (
        uw["field_coverage"]["gpa"]["rule_usable"] and "gpa" not in uw["catalog_gaps"]
    )
    assert any(
        i["reason_code"] == "GPA_SCOPE_MISMATCH"
        for i in uw["reference_profile_comparison_issues"]
    )


def test_recommended_gpa_is_not_counted_as_a_verified_hard_rule():
    uiuc = row(audited(), "uiuc-mcs-urbana")
    assert uiuc["field_coverage"]["gpa"]["evidence_bound"]
    assert (
        not uiuc["field_coverage"]["gpa"]["rule_usable"]
        and uiuc["gpa_recommendation_only"]
    )


def test_explicit_verified_no_minimum_policy_is_a_usable_rule():
    programs, sources = load_seed(M35_SEED)
    p = next(p for p in programs if p.program_id == "uiuc-mcs-urbana")
    p.gpa = GPARequirement(no_hard_minimum=True)
    for sid in p.field_sources["gpa"]:
        sources[sid].verified_values["gpa"] = {"gpa": p.gpa.model_dump(mode="json")}
    result = row(audited(programs, sources), p.program_id)
    assert result["field_coverage"]["gpa"]["rule_usable"]
    assert not result["gpa_recommendation_only"]


def test_raw_calculable_tuition_is_not_verified_when_credit_evidence_breaks():
    programs, sources = load_seed(M35_SEED)
    p = next(p for p in programs if p.program_id == "uw-ece-msece-pmp-seattle")
    p.required_credits = 47
    result = row(audited(programs, sources), p.program_id)
    assert result["field_coverage"]["tuition"]["evidence_bound"]
    assert not result["field_coverage"]["credits"]["evidence_bound"]
    assert result["tuition"]["upper_usd"] is None
    assert not result["field_coverage"]["tuition"]["rule_usable"]


@pytest.mark.parametrize(
    "failure", ["missing", "conflict", "wrong_program", "wrong_intake"]
)
def test_present_source_ids_do_not_count_as_usable_when_evidence_is_invalid(failure):
    programs, sources = load_seed(M35_SEED)
    p = next(p for p in programs if p.program_id == "uw-ece-msece-pmp-seattle")
    sid = p.field_sources["gpa"][0]
    if failure == "missing":
        del sources[sid]
    elif failure == "conflict":
        sources[sid].verification_status = "conflict"
    elif failure == "wrong_program":
        sources[sid].program_id = "cmu-msaii-pittsburgh"
    else:
        sources[sid].applicable_intake = "2028-fall"
    result = row(audited(programs, sources), p.program_id)
    assert not result["field_coverage"]["gpa"]["evidence_bound"]
    assert "gpa" in result["catalog_gaps"]


@pytest.mark.parametrize("year", [2000, 2027])
def test_old_or_future_cohort_is_not_current_tier_evidence(year):
    programs, sources = load_seed(M35_SEED)
    p = next(p for p in programs if p.program_id == "cmu-msaii-pittsburgh")
    p.admission_evidence[0].cycle_year = year
    for sid in p.field_sources["admission_evidence"]:
        sources[sid].verified_values["admission_evidence"] = {
            "admission_evidence": [
                e.model_dump(mode="json") for e in p.admission_evidence
            ]
        }
    result = row(audited(programs, sources), p.program_id)
    assert result["field_coverage"]["admission_evidence"]["evidence_bound"]
    assert (
        not result["reference_supported_tiers"]
        and not result["reference_formal_evidence_ready"]
    )


def test_snapshot_audit_is_order_invariant_and_does_not_mutate_inputs():
    programs, sources = load_seed(M35_SEED)
    before = [p.model_dump(mode="json") for p in programs]
    first = audited(programs, sources)
    second = audited(list(reversed(programs)), dict(reversed(list(sources.items()))))
    assert first == second and before == [p.model_dump(mode="json") for p in programs]


def inputs():
    return (
        json.loads(INDEX.read_text(encoding="utf-8")),
        json.loads(REVIEW.read_text(encoding="utf-8")),
        load_seed(M35_SEED)[0],
    )


def test_candidate_links_preserve_origin_and_queued_leads_remain_ineligible():
    index, review, programs = inputs()
    before = deepcopy(index)
    result = screen_candidates(index, review, programs)
    assert (
        result["summary"]["total"] == 83
        and result["summary"]["source_reports_halted"] == 4
    )
    assert result["summary"]["screening_counts"] == {
        "already_linked_identity": 10,
        "first_batch_review": 10,
        "halt_report_needs_official_check": 4,
        "not_selected": 59,
    }
    assert not any(r["recommendation_eligible"] for r in result["inventory"])
    assert all(
        r["promotion_status"] == "not_imported" for r in result["first_expansion_batch"]
    )
    assert index == before
    assert {
        p.candidate_source_id for p in programs if p.program_id.startswith("cmu-")
    } == {"official-cmu-program-comparison"}


@pytest.mark.parametrize(
    "failure",
    [
        "duplicate_candidate",
        "promotion",
        "wrong_intake",
        "unknown_link",
        "duplicate_program_link",
        "duplicate_queue",
        "halted_queue",
        "wrong_url",
        "imported_queue",
    ],
)
def test_invalid_candidate_review_cannot_silently_promote_or_duplicate(failure):
    index, review, programs = inputs()
    if failure == "duplicate_candidate":
        index["rows"][1]["source_id"] = index["rows"][0]["source_id"]
    elif failure == "promotion":
        index["rows"][0]["recommendation_eligible"] = 1
    elif failure == "wrong_intake":
        review["target_intake"] = "2028-fall"
    elif failure == "unknown_link":
        review["catalog_links"][0]["program_id"] = "unknown-program"
    elif failure == "duplicate_program_link":
        review["catalog_links"][0]["program_id"] = review["catalog_links"][1][
            "program_id"
        ]
    elif failure == "duplicate_queue":
        review["first_expansion_batch"].append(review["first_expansion_batch"][0])
    elif failure == "halted_queue":
        next(
            r
            for r in index["rows"]
            if r["source_id"]
            == review["first_expansion_batch"][0]["candidate_source_id"]
        )["source_reports_halted"] = 1
    elif failure == "wrong_url":
        review["first_expansion_batch"][0]["official_url"] = "https://attacker.example/"
    else:
        review["first_expansion_batch"][0]["promotion_status"] = "imported"
    with pytest.raises(ValueError):
        screen_candidates(index, review, programs)


def test_audit_never_needs_network_or_model(monkeypatch):
    from gradmatch.providers import OpenAIProvider

    def forbidden(*args, **kwargs):
        raise AssertionError("Network/model call in an offline audit")

    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(OpenAIProvider, "generate", forbidden)
    report = build_report(as_of=AS_OF, seed=M35_SEED, review_path=REVIEW)
    assert report["paid_model_requests"] == 0 and not report["datapoints_accessed"]
    assert (
        not report["expanded_catalog_gate_met"] and not report["formal_benchmark_run"]
    )
