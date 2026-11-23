"""Audit applicant-reported admissions coverage against pinned recommendation identities."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from gradmatch.admission_history import gpa_band, write_preview
from gradmatch.broad_catalog import build_broad_catalog
from gradmatch.catalog import load_seed
from gradmatch.schemas import GPA, GPA_SCOPE_LABELS, Intake
from gradmatch.storage import PROJECT_ROOT


MAPPINGS = PROJECT_ROOT / "data/review/admission_dp_pilot.json"
SEED = PROJECT_ROOT / "data/catalog/m61j_seed.json"
GPA_SCOPES = tuple(GPA_SCOPE_LABELS)
TERMS = {"fall": "Fall", "spring": "Spring", "summer": "Summer", "winter": "Winter"}
OUTCOMES = {
    "Admit": "reported_admit",
    "Reject": "reported_reject",
    "Waitlist": "waitlist",
    "Withdraw": "withdraw",
    "\u9ed8\u62d2": "no_explicit_decision",
    None: "no_explicit_decision",
}
UNKNOWN_GPA = (None, None, None)


def load_mappings():
    manifest = json.loads(MAPPINGS.read_text(encoding="utf-8"))
    programs, sources = load_seed(SEED)
    _, context = build_broad_catalog(programs, sources)
    ids_by_tracker = {entry["source_id"]: pid for pid, entry in context["entries"].items()}
    rows = manifest["programs"]
    for field in ("source_program_id", "tracker_id", "program_id"):
        if len({row[field] for row in rows}) != len(rows):
            raise ValueError("Duplicate program identity in the pilot mappings.")
    for row in rows:
        program_id = row["program_id"]
        tracker_id = row["tracker_id"]
        if ids_by_tracker.get(tracker_id) != program_id:
            raise ValueError(f"Program binding differs from the recommendation catalog for {program_id}.")
        last_cycle = row.get("latest_unambiguous_cycle")
        if last_cycle is not None and (type(last_cycle) is not int or not 2020 <= last_cycle <= 2100):
            raise ValueError(f"Invalid route cutoff for {program_id}.")
    return manifest


def reported_gpa(applicant):
    try:
        value, scale = (Decimal(str(applicant.get(key))) for key in ("gpa", "gpa_scale"))
    except InvalidOperation:
        return UNKNOWN_GPA
    if not (value.is_finite() and scale.is_finite() and scale > 0 and 0 <= value <= scale):
        return UNKNOWN_GPA
    scope = applicant.get("gpa_scope")
    if isinstance(scope, str):
        scope = scope.strip().lower() or None
    return value, scale, scope if scope is None or scope in GPA_SCOPES else "unrecognized"


def summarize_program(mapping, buckets, coverage, comparison, *, include_background=False):
    latest = {}
    duplicate_rows = 0
    conflicting_cycles = 0
    for (person, year), submissions in buckets.items():
        duplicate_rows += len(submissions) - 1
        statuses = {status for status, _, _ in submissions}
        gpas = {gpa for _, gpa, _ in submissions}
        if len(statuses) > 1:
            conflicting_cycles += 1
        if person not in latest or year > latest[person][0]:
            status = next(iter(statuses)) if len(statuses) == 1 else "conflicting_reports"
            gpa = next(iter(gpas)) if len(gpas) == 1 else UNKNOWN_GPA
            same_background = all(matches for _, _, matches in submissions)
            latest[person] = year, status, gpa, same_background

    all_outcomes, same_scale, same_scope, unknown_scope = (Counter() for _ in range(4))
    assumed_overall = Counter()
    gpa_bands = defaultdict(Counter)
    background_bands = defaultdict(Counter)
    for _, status, (value, scale, scope), same_background in latest.values():
        all_outcomes[status] += 1
        if scale != comparison.scale or status == "conflicting_reports":
            continue
        same_scale[status] += 1
        assumed = scope is None and comparison.scope == "overall"
        if scope == comparison.scope:
            same_scope[status] += 1
        elif scope not in GPA_SCOPES:
            unknown_scope[status] += 1
            if assumed:
                assumed_overall[status] += 1
        if (scope == comparison.scope or assumed) and status in {"reported_admit", "reported_reject"}:
            band = gpa_band(value, scale)
            outcome = "admitted" if status == "reported_admit" else "rejected"
            counts = gpa_bands[band]
            counts[outcome] += 1
            counts["assumed_overall"] += int(assumed)
            if include_background and same_background:
                background_bands[band][outcome] += 1
    report = {
        "program_id": mapping["program_id"],
        "source_reports_all_cycles": coverage["matched"],
        "rejected_identity_rows": coverage["rejected_identity"],
        "rejected_route_rows": coverage["rejected_route"],
        "source_reports_in_window": sum(len(submissions) for submissions in buckets.values()),
        "duplicate_reports_in_window": duplicate_rows,
        "conflicting_applicant_cycles": conflicting_cycles,
        "earlier_cycles_for_repeat_applicants": len(buckets) - len(latest),
        "distinct_applicants_in_window": len(latest),
        "outcomes": dict(sorted(all_outcomes.items())),
        "same_gpa_scale_outcomes": dict(sorted(same_scale.items())),
        "same_gpa_scale_unknown_scope_outcomes": dict(sorted(unknown_scope.items())),
        "same_gpa_scale_and_scope_outcomes": dict(sorted(same_scope.items())),
        "same_scale_and_scope_admit_count": same_scope["reported_admit"],
        "same_gpa_scale_assumed_overall_outcomes": dict(sorted(assumed_overall.items())),
        "same_gpa_scale_and_effective_scope_outcomes": dict(sorted((same_scope + assumed_overall).items())),
        "gpa_bands": {str(band): {key: counts[key] for key in ("admitted", "rejected", "assumed_overall")}
                      for band, counts in sorted(gpa_bands.items())},
    }
    if include_background:
        report["background_gpa_bands"] = {str(band): dict(sorted(counts.items()))
                                         for band, counts in sorted(background_bands.items())}
    return report


def audit(export, manifest, *, intake, comparison, matches_background=None):
    records = export.get("records")
    if (export.get("complete") is not True or not isinstance(records, list)
            or len(records) != export.get("saved_records") or len(records) != export.get("reported_total_at_start")):
        raise ValueError("The admissions export is incomplete or its record counts disagree.")
    source_year = datetime.fromisoformat(export["downloaded_at_utc"]).year
    last_cycle = min(intake.year - 1, source_year)
    cycles = range(last_cycle - 2, last_cycle + 1)
    by_source = {row["source_program_id"]: row for row in manifest["programs"]}
    coverage = defaultdict(Counter)
    groups = defaultdict(lambda: defaultdict(list))
    for record in records:
        program, decision, applicant = record["p"], record["d"], record["a"]
        source_id = program["id"]
        reported_id = decision["program_id"]
        if source_id not in by_source and reported_id not in by_source:
            continue
        if source_id != reported_id:
            for known_id in {source_id, reported_id} & by_source.keys():
                coverage[known_id]["rejected_identity"] += 1
            continue
        mapping = by_source[source_id]
        person = decision["applicant_id"]
        if (not isinstance(person, str) or not person.strip() or applicant["id"] != person or
                (program["school"], program["program"], program["degree"]) !=
                (mapping["source_school"], mapping["source_program"], mapping["source_degree"])):
            coverage[source_id]["rejected_identity"] += 1
            continue
        year = decision["academic_year"]
        last_cycle_for_route = mapping.get("latest_unambiguous_cycle")
        if last_cycle_for_route is not None and (type(year) is not int or year > last_cycle_for_route):
            coverage[source_id]["rejected_route"] += 1
            continue
        coverage[source_id]["matched"] += 1
        if type(year) is int and year in cycles and decision["semester"] == TERMS[intake.term]:
            status = OUTCOMES.get(decision["result"], "other")
            same_background = matches_background(applicant) if matches_background else False
            groups[source_id][person, year].append((status, reported_gpa(applicant), same_background))

    return {
        "version": manifest["version"],
        "mode": "local_coverage_audit",
        "downloaded_at_utc": export["downloaded_at_utc"],
        "source_reports": len(records),
        "target_intake": intake.key,
        "report_cycles": list(cycles),
        "comparison_gpa_scale": format(comparison.scale.normalize(), "f"),
        "comparison_gpa_scope": comparison.scope,
        "missing_gpa_scope_assumption": "overall",
        "programs": [summarize_program(mapping, groups[source_id], coverage[source_id], comparison,
                                       include_background=matches_background is not None)
                     for source_id, mapping in by_source.items()],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Local admissions JSON export")
    parser.add_argument("--intake-year", type=int, default=2027)
    parser.add_argument("--intake-term", choices=TERMS, default="fall")
    parser.add_argument("--gpa-scale", default="4")
    parser.add_argument("--gpa-scope", choices=GPA_SCOPES, default="overall")
    parser.add_argument("--write-preview", action="store_true", help="Enable the local recommendation-card preview for this comparison basis")
    args = parser.parse_args()
    try:
        intake = Intake(year=args.intake_year, term=args.intake_term)
        comparison = GPA(value=0, scale=args.gpa_scale, scope=args.gpa_scope)
        payload = args.input.read_bytes()
        report = audit(json.loads(payload), load_mappings(), intake=intake, comparison=comparison)
        report["source_sha256"] = hashlib.sha256(payload).hexdigest()
        directory = PROJECT_ROOT / "work/admissions_dp" / uuid4().hex[:12]
        directory.mkdir(parents=True)
        path = directory / "coverage.json"
        path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(f"Audited {len(report['programs'])} programs. Aggregate report: {path}")
        if args.write_preview:
            print(f"Recommendation-card preview: {write_preview(report, intake)}")
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Admissions coverage audit failed ({type(error).__name__}). Check the export and arguments.\n")


if __name__ == "__main__":
    main()
