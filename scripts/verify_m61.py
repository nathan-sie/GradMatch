"""Verify M6.1a audit coverage, provenance, no network/model calls and DB immutability."""

import argparse
import json
import socket
import subprocess
import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from gradmatch.catalog_audit import markdown_report
from gradmatch.catalog import M35_SEED
from gradmatch.providers import OpenAIProvider
from gradmatch.storage import DEFAULT_DATABASE, PROJECT_ROOT
from scripts.audit_catalog import LEGACY_REVIEW, build_report, sha256


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Only after the current source passed the suite.",
    )
    args = parser.parse_args()
    directory = args.output_dir or PROJECT_ROOT / "work/m61" / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    candidate_db = PROJECT_ROOT / "work/csgrad_candidates.db"
    tracker = PROJECT_ROOT / "work/csgrad-school-list.json"
    databases = [p for p in [DEFAULT_DATABASE, candidate_db] if p.exists()]
    before = {p.name: sha256(p) for p in databases}
    report = dict(
        milestone="M6.1a",
        scope="Audit and first research batch; full M6 is incomplete",
        tests="not_run",
        status="failed",
        paid_model_requests=0,
        network_requests_in_audit=0,
    )
    if not args.skip_tests:
        check = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        (directory / "offline_tests.txt").write_text(
            check.stdout + check.stderr, encoding="utf-8", newline="\n"
        )
        report["tests"] = "passed" if check.returncode == 0 else "failed"
        print(check.stdout.strip().splitlines()[-1])
        if check.returncode:
            (directory / "verification.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            return 1

    def forbidden(*args, **kwargs):
        raise AssertionError("Offline audit attempted a network/model call")

    with (
        patch.object(socket, "getaddrinfo", forbidden),
        patch.object(socket, "create_connection", forbidden),
        patch.object(OpenAIProvider, "generate", forbidden),
    ):
        audit = build_report(
            seed=M35_SEED,
            review_path=LEGACY_REVIEW,
            as_of=date(2026, 11, 19),
            candidate_database=candidate_db if candidate_db.exists() else None,
            original_tracker=tracker if tracker.exists() else None,
        )
    after = {p.name: sha256(p) for p in databases}
    if before != after:
        raise ValueError("Audit or tests changed an existing database")
    summary = audit["catalog"]["summary"]
    checks = dict(
        unique_programs=len({r["program_id"] for r in audit["catalog"]["programs"]})
        == summary["programs"],
        source_totals_reconcile=sum(
            r["source_count"] for r in audit["catalog"]["programs"]
        )
        == summary["sources"],
        candidate_counts_reconcile=sum(
            audit["candidates"]["summary"]["screening_counts"].values()
        )
        == audit["candidates"]["summary"]["total"],
        no_candidate_promoted=not any(
            r["recommendation_eligible"] for r in audit["candidates"]["inventory"]
        ),
        no_model_or_network=True,
        databases_unchanged=before == after,
        no_benchmark_score_claimed=not audit["formal_benchmark_run"],
    )
    report.update(
        status="passed" if all(checks.values()) else "failed",
        checks=checks,
        database_sha256=after,
        full_m6_complete=False,
        expanded_catalog_gate_met=audit["expanded_catalog_gate_met"],
        programs=summary["programs"],
        official_sources=summary["sources"],
        candidate_rows=audit["candidates"]["summary"]["total"],
        seed_data_hash=audit["catalog"]["data_hash"],
    )
    (directory / "catalog_audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (directory / "catalog_audit.md").write_text(
        markdown_report(audit), encoding="utf-8", newline="\n"
    )
    (directory / "verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        f"M6.1a {report['status']}: {summary['programs']} reviewed programs, {audit['candidates']['summary']['total']} candidate leads; no API calls or database changes."
    )
    print("Evidence directory: " + str(directory.resolve()))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
