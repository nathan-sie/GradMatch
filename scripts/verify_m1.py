"""Verify M1 offline: typed evidence, database round-trip, rules and real UI tests."""

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from gradmatch.catalog import coverage_rows, load_seed, read_catalog
from gradmatch.constraints import check_constraints
from gradmatch.schemas import ApplicantProfile
from gradmatch.storage import PROJECT_ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=PROJECT_ROOT / "work" / "m1_verification.json")
    args = parser.parse_args()
    report = {"milestone": "M1", "verified_at": datetime.now(timezone.utc).isoformat(),
              "status": "failed", "manual_acceptance": "pending", "data_mode": "snapshot",
              "model_api_calls": 0, "search_api_calls": 0}
    code = 1
    try:
        expected, expected_sources = load_seed()
        programs, sources = read_catalog()
        if not 8 <= len(expected) <= 12:
            raise ValueError("M1 requires 8–12 reviewed program identities.")
        current = {program.program_id: program for program in programs}
        for program in expected:
            if program.program_id not in current or current[program.program_id] != program:
                raise ValueError("Database records differ from the validated seed; reimport first.")
        if any(source_id not in sources or sources[source_id] != source for source_id, source in expected_sources.items()):
            raise ValueError("Database evidence differs from the validated snapshots.")
        coverage = coverage_rows(expected, expected_sources)
        work = PROJECT_ROOT / "work"
        work.mkdir(exist_ok=True)
        (work / "m1_catalog_coverage.json").write_text(json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8")
        md = ["# M1 Catalog Coverage", "", "Verified identities and computable tuition do not establish readiness for admission-tier recommendations.", "",
              "| University / campus | Credits | Estimated full-program tuition (USD) | Rate year | Official sources | Needs verification |",
              "| --- | ---: | ---: | --- | ---: | --- |"]
        for row in coverage:
            md.append(f"| {row['university']} / {row['campus']} | {row['required_credits'] or 'Unknown'} | {row['tuition_estimate_usd'] or 'Unknown'} | {row['rate_year'] or 'Unknown'} | {row['source_count']} | {', '.join(row['missing_fields'])} |")
        (work / "m1_catalog_coverage.md").write_text("\n".join(md) + "\n", encoding="utf-8")
        profile = ApplicantProfile(gpa={"value": "3.5", "scale": "4", "scope": "last_60_semester"},
            tuition_budget_usd="70000", intake={"year": 2027, "term": "fall"},
            english_status="known", english={"version": "toefl_120", "total": "100", "test_date": "2025-11-01"})
        samples = {"70000": [], "50000": []}
        for budget in samples:
            candidate = ApplicantProfile.model_validate({**profile.model_dump(), "tuition_budget_usd": budget,
                "profile_version": 1 if budget == "70000" else 2})
            samples[budget] = [check_constraints(candidate, program, sources, as_of=date(2026, 11, 13)).model_dump(mode="json") for program in expected]
        (work / "m1_example_checks.json").write_text(json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8")
        result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        report.update(programs=len(expected), official_sources=len(expected_sources),
            computable_tuition=sum(row["tuition_estimate_usd"] is not None for row in coverage),
            incomplete_tuition=sum(row["tuition_estimate_usd"] is None for row in coverage),
            catalog_version=expected[0].catalog_version, checks_as_of="2026-11-13",
            test_output=result.stdout, test_exit_code=result.returncode,
            recommendation_ready=0, status="passed" if result.returncode == 0 else "failed")
        code = result.returncode
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"M1 {report['status']}; report: {args.report.resolve()}")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
