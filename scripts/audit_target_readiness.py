"""Check where local applicant reports could support a reviewed Target recommendation."""

import argparse
from datetime import date
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from gradmatch.admission_history import gpa_band
from gradmatch.catalog import current_seed, load_seed
from gradmatch.constraints import check_constraints
from gradmatch.ranking import RecommendationDraft
from gradmatch.schemas import GPA
from gradmatch.session import tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.tiers import RUBRIC_VERSION
from gradmatch.validation import tier_errors
from scripts.audit_admission_dp import audit, load_mappings


COMPUTER_SCIENCE_LABELS = {
    "cs", "computer science", "computer science and technology",
    "\u8ba1\u7b97\u673a", "\u8ba1\u7b97\u673a\u79d1\u5b66", "\u8ba1\u7b97\u673a\u79d1\u5b66\u4e0e\u6280\u672f",
}
REPORTED_EXPERIENCE = {
    "research": ("research_domestic_count", "research_overseas_count"),
    "work_experience": ("internship_domestic_count", "internship_overseas_count"),
}


def same_reported_background(applicant, profile):
    """Screen a CS fixture for reported categories before manual comparability review."""
    major = applicant.get("ug_major")
    if not isinstance(major, str) or " ".join(major.casefold().split()) not in COMPUTER_SCIENCE_LABELS:
        return False
    for dimension, fields in REPORTED_EXPERIENCE.items():
        if getattr(profile, dimension) and any(
            type(count) is int and count > 0 for count in (applicant.get(field) for field in fields)
        ):
            return True
    return False


def check_target(program, sources, profile, as_of, coverage):
    band = str(gpa_band(profile.gpa.value, profile.gpa.scale))
    outcomes = coverage["gpa_bands"].get(band, {})
    screened = coverage["background_gpa_bands"].get(band, {})
    counts = {
        "program_id": coverage["program_id"],
        "gpa_band_reports": {key: outcomes.get(key, 0) for key in ("admitted", "rejected")},
        "reported_background_matches": {key: screened.get(key, 0) for key in ("admitted", "rejected")},
        "background_review_candidates_at_least_two": screened.get("admitted", 0) >= 2,
    }
    if program is None:
        return {
            **counts,
            "official_eligibility_passed": False,
            "official_blockers": [{"rule": "identity", "status": "unknown", "reason": "MISSING_OFFICIAL_PROGRAM_RECORD"}],
            "current_tier_validation_errors": ["MISSING_OFFICIAL_PROGRAM_RECORD"],
            "target_supported": False,
        }
    assessment = check_constraints(profile, program, sources, as_of=as_of)
    item = RecommendationDraft(
        program_id=program.program_id, tier="Target",
        goal_feature_ids=[feature.feature_id for feature in program.goal_features
                          if feature.goal in {profile.goal, "mixed"}],
        tier_evidence_ids=[evidence.evidence_id for evidence in program.admission_evidence
                           if evidence.kind == "admitted_case" and "Target" in evidence.permitted_tiers],
        comparison_dimensions=["gpa", "major", "research", "work_experience"],
        lower_risk_rationale=None,
        limitations=["Target is an evidence-based planning label."],
    )
    errors = sorted(set(tier_errors(item, profile, program, sources, as_of)))
    return {
        **counts,
        "official_eligibility_passed": assessment.recommendation_ready,
        "official_blockers": [{"rule": check.rule_id, "status": check.status, "reason": check.reason_code}
                              for check in assessment.checks if check.status in {"unknown", "fail"}],
        "current_tier_validation_errors": errors,
        "target_supported": assessment.recommendation_ready and not errors,
    }


def review_profiles(export, manifest, programs, sources, gpas, as_of):
    reference = tiering_profile()
    by_id = {program.program_id: program for program in programs}
    scenarios = []
    for score in gpas:
        gpa = GPA(value=score, scale=reference.gpa.scale, scope=reference.gpa.scope)
        profile = reference.model_copy(update={"gpa": gpa})
        coverage = audit(
            export, manifest, intake=profile.intake, comparison=profile.gpa,
            matches_background=lambda applicant: same_reported_background(applicant, profile),
        )
        scenarios.append({
            "gpa": gpa.model_dump(mode="json"), "cycles": coverage["report_cycles"],
            "programs": [check_target(by_id.get(row["program_id"]), sources, profile, as_of, row)
                         for row in coverage["programs"]],
        })
    return {
        "mode": "local_target_readiness_review",
        "as_of": as_of.isoformat(),
        "rubric": RUBRIC_VERSION,
        "profile": {"fictional": True, "major": reference.major, "goal": reference.goal,
                    "intake": reference.intake.key, "budget_usd": str(reference.tuition_budget_usd)},
        "missing_gpa_scope_assumption": "overall",
        "scenarios": scenarios,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--gpa", action="append", help="Fictional overall GPA on a 4-point scale. Repeat for multiple scenarios.")
    args = parser.parse_args()
    try:
        data = args.input.read_bytes()
        seed = current_seed()
        programs, sources = load_seed(seed)
        config = json.loads((PROJECT_ROOT / "config/eval.json").read_text(encoding="utf-8"))
        report = review_profiles(json.loads(data), load_mappings(), programs, sources,
                                 args.gpa or ["3.50", "3.80"], date.fromisoformat(config["evaluation_date"]))
        report["source_sha256"] = hashlib.sha256(data).hexdigest()
        report["catalog_seed"] = seed.name
        directory = PROJECT_ROOT / "work/admissions_dp" / uuid4().hex[:12]
        directory.mkdir(parents=True)
        path = directory / "target_readiness.json"
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Local Target readiness report: {path}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Target readiness audit failed ({type(error).__name__}). Check the export and GPA arguments.\n")


if __name__ == "__main__":
    main()
