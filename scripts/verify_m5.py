"""M5 offline checks and optional inspection of an actual exported cloud session.

Never invokes the configured local model. Fixture pilot rows test wiring only.
"""

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from gradmatch.catalog import load_seed
from gradmatch.config import load_settings
from gradmatch.service import start_task
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import blocking_validation_errors
from scripts.m5_fixtures import AS_OF, FixtureProvider


def fixture_pilot():
    rows = []
    for budget in ["140000", "100000", "30000"]:
        group = []
        for strategy in ["fixed", "react", "plan"]:
            programs, sources = load_seed()
            session = Session(profile=tiering_profile())
            session.update({"tuition_budget_usd": budget})
            result = start_task(
                session,
                request_id=str(uuid4()),
                programs=programs,
                sources=sources,
                settings=replace(load_settings(), enabled=False),
                as_of=AS_OF,
                strategy=strategy,
                provider=FixtureProvider(),
            )
            assert result["status"] not in {"error", "budget_exhausted", "needs_input"}
            assert (
                result["model_status"] == "test_stub"
                and not result["validation_errors"]
            )
            row = dict(
                strategy=strategy,
                fictional_budget_usd=budget,
                status=result["status"],
                recommendations=sorted(
                    p["program_id"] for p in result["recommendations"]
                ),
                pending=sorted(p["program_id"] for p in result["pending_verification"]),
                excluded=sorted(p["program_id"] for p in result["excluded"]),
                data_hash=result["data_hash"],
                shared_limits=result["task_usage"]["limits"],
                fixture_model_calls=result["task_usage"]["model_calls"],
                fixture_tool_calls=result["task_usage"]["tool_calls"],
                actual_model_requests=0,
                tokens=None,
                cost_usd=None,
            )
            rows.append(row)
            group.append(row)
        for key in [
            "recommendations",
            "pending",
            "excluded",
            "data_hash",
            "shared_limits",
        ]:
            assert all(r[key] == group[0][key] for r in group)
    return dict(
        kind="OFFLINE_FIXTURES_NOT_A_BENCHMARK",
        status="passed",
        rows=rows,
        notice="Tests shared entry, caps and validator only. No accuracy, latency, token or cost comparison is claimed.",
    )


def inspect_actual_session(path):
    raw = path.read_bytes()
    data = json.loads(raw)
    task = data.get("agent_task") or {}
    plan = task.get("plan") or {}
    usage = data.get("usage", [])
    revisions = plan.get("revisions", [])
    result = data.get("result") or {}
    checks = {
        "plan_strategy": task.get("strategy") == "plan",
        "real_metered_requests": bool(usage)
        and all(u.get("response_id") and u.get("status") == "completed" for u in usage),
        "within_eight_requests": len(usage) <= 8,
        "request_count_matches": task.get("model_calls") == len(usage),
        "initial_and_revised_plan": len(revisions) >= 2
        and revisions[0]["reason_code"] == "INITIAL_PLAN"
        and any(r["reason_code"] == "PROFILE_UPDATED" for r in revisions[1:]),
        "steps_completed": bool(revisions)
        and revisions[-1]["status"] == "completed"
        and all(s["status"] == "done" for s in revisions[-1]["steps"]),
        "within_replan_cap": 0 < plan.get("replans", 0) <= 3,
        "validated_result": result.get("status")
        in {"completed", "insufficient_evidence", "infeasible"}
        and result.get("validation_errors") is not None
        and not blocking_validation_errors(result),
        "budget_exclusion": any(
            p["program_id"] == "cmu-msaii-pittsburgh"
            and "TUITION_EXCEEDS_BUDGET" in p.get("reason_codes", [])
            for p in result.get("excluded", [])
        ),
    }
    return dict(
        status="passed" if all(checks.values()) else "failed",
        checks=checks,
        export_sha256=hashlib.sha256(raw).hexdigest(),
        task_id=task.get("task_id"),
        model_requests=len(usage),
        usage=usage,
        tool_calls=task.get("tool_calls"),
        page_requests=task.get("page_requests"),
        final_profile_version=result.get("profile_version"),
        final_status=result.get("status"),
        plans=[
            {
                k: r.get(k)
                for k in [
                    "revision",
                    "reason_code",
                    "profile_version",
                    "evidence_version",
                    "status",
                ]
            }
            | {
                "steps": [
                    {
                        k: s.get(k)
                        for k in [
                            "step_id",
                            "tool",
                            "status",
                            "done_criteria",
                            "result_refs",
                        ]
                    }
                    for s in r["steps"]
                ]
            }
            for r in revisions
        ],
        notice="Sanitized proof from the exported hosted session; no key, messages or full applicant profile included.",
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--session",
        type=Path,
        help="Inspect an actual cloud export; never sends it to a model.",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Only after checks passed on this revision.",
    )
    args = parser.parse_args()
    directory = args.output_dir or PROJECT_ROOT / "work/m5" / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    report = dict(
        milestone="M5",
        verified_at=datetime.now(timezone.utc).isoformat(),
        offline="not_run",
        actual_cloud="not_run",
        milestone_complete=False,
    )
    if not args.skip_tests:
        check = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        (directory / "offline_tests.txt").write_text(
            check.stdout + check.stderr, encoding="utf-8", newline="\n"
        )
        report["offline"] = "passed" if check.returncode == 0 else "failed"
        print(check.stdout.strip().splitlines()[-1])
        if check.returncode:
            (directory / "verification.json").write_text(
                json.dumps(report, indent=2) + "\n", encoding="utf-8"
            )
            return 1
    report["fixture_pilot"] = fixture_pilot()
    if args.session:
        report["actual_cloud"] = inspect_actual_session(args.session)
        report["milestone_complete"] = (
            report["actual_cloud"]["status"] == "passed"
            and report["offline"] == "passed"
        )
    (directory / "verification.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(
        "Offline fixtures passed (not a benchmark). Actual cloud: "
        + str(
            report["actual_cloud"]
            if isinstance(report["actual_cloud"], str)
            else report["actual_cloud"]["status"]
        )
    )
    print("Evidence directory: " + str(directory))
    return (
        1
        if isinstance(report["actual_cloud"], dict)
        and report["actual_cloud"]["status"] == "failed"
        else 0
    )


if __name__ == "__main__":
    raise SystemExit(main())
