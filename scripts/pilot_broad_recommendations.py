"""Run a bounded 83-program plan-and-replan pilot with a fictional applicant."""

import argparse
from dataclasses import replace
from datetime import date
from decimal import Decimal
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from gradmatch.catalog import load_seed
from gradmatch.config import load_settings
from gradmatch.providers import OpenAIProvider
from gradmatch.service import export_session, start_task
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import blocking_validation_errors
from scripts.verify_broad_recommendations import BroadFixture


AS_OF = date(2026, 11, 21)
REQUEST_LIMIT = 6
FOLLOWUP = "Change my tuition budget to 50000"


def write_result(path, data):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def assess_turn(result, *, live_model, reason):
    task = result["task_usage"]
    plan = (task.get("plan") or {}).get("revisions", [])
    rows = result.get("preliminary_recommendations", [])
    completed_ranking = any(item["purpose"] == "rank" and item["status"] == "completed"
                            and item.get("response_id") for item in result["usage"])
    return {
        "validated": result["status"] in {"completed", "insufficient_evidence"}
        and result.get("validation_passed", False) and not blocking_validation_errors(result),
        "screened_full_pool": result.get("catalog_program_count") == 83
        and len(set(result.get("retrieved_program_ids", []))) == 83,
        "community_candidate_selected": any(row["program_id"].startswith("community-")
                                           and row.get("personalized_tier") is None for row in rows),
        "plan_completed": bool(plan and plan[-1]["status"] == "completed"
                               and any(revision["reason_code"] == reason for revision in plan)),
        "expected_model_mode": completed_ranking if live_model else result["model_status"] == "test_stub",
        "snapshot_only": task["page_requests"] == 0 and task["search_queries"] == 0,
    }


def pilot(settings, directory, *, live_model):
    provider = None if live_model else BroadFixture()
    session = Session(profile=tiering_profile())
    programs, sources = load_seed()
    turns = []
    checks = {}

    for name, message, reason in [("initial", None, "INITIAL_PLAN"),
                                  ("lower_budget", FOLLOWUP, "PROFILE_UPDATED")]:
        previous = session.profile.model_dump()
        result = start_task(session, request_id=str(uuid4()), programs=programs, sources=sources,
                            settings=settings, as_of=AS_OF, strategy="plan", data_mode="snapshot",
                            recommendation_scope="broad", provider=provider, message=message)
        turns.append(result)
        turn_checks = assess_turn(result, live_model=live_model, reason=reason)
        if name == "lower_budget":
            current = session.profile.model_dump()
            turn_checks["only_budget_changed"] = current == {
                **previous, "profile_version": previous["profile_version"] + 1,
                "tuition_budget_usd": Decimal("50000"),
            }
            turn_checks["same_task"] = turns[0]["task_id"] == result["task_id"]
            turn_checks["over_budget_program_excluded"] = any(
                row["program_id"] == "cmu-msaii-pittsburgh"
                and "TUITION_EXCEEDS_BUDGET" in row.get("reason_codes", [])
                for row in result.get("excluded", [])
            )
        checks[name] = turn_checks
        write_result(directory / "session.json", {"session": export_session(session), "turns": turns})
        print(f"{name}: {result['status']}, {result['model_calls']} model calls, checks {turn_checks}", flush=True)
        if not all(turn_checks.values()):
            break

    costs = [item.get("estimated_cost_usd") for item in session.usage]
    report = {
        "status": "passed" if len(turns) == 2 and all(all(turn.values()) for turn in checks.values()) else "failed",
        "mode": "live_model" if live_model else "offline_fixture",
        "as_of": AS_OF.isoformat(),
        "checks": checks,
        "paid_request_limit": REQUEST_LIMIT if live_model else 0,
        "paid_requests_attempted": len(session.usage) if live_model else 0,
        "estimated_cost_usd": str(sum(Decimal(value) for value in costs)) if live_model and costs and all(value is not None for value in costs) else None,
        "usage": session.usage,
        "latency_ms_by_turn": [result["service_latency_ms"] for result in turns],
        "recommendation_data_hash": turns[0].get("recommendation_data_hash"),
        "benchmark_scores": "not_measured",
    }
    write_result(directory / "pilot.json", report)
    print(f"{report['mode']}: {report['status']}. Evidence: {directory}", flush=True)
    return int(report["status"] != "passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-model", action="store_true", help="Enable up to six metered OpenAI calls.")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    settings = load_settings()
    if args.live_model and not settings.ready:
        parser.error("The local OpenAI configuration must be enabled before a live pilot.")
    directory = args.output_dir or PROJECT_ROOT / "work/m63/pilot" / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    settings = replace(settings, limits={**settings.limits, "max_model_calls_per_session": REQUEST_LIMIT})
    if args.live_model:
        return pilot(settings, directory, live_model=True)
    with patch.object(OpenAIProvider, "generate", side_effect=AssertionError("Offline pilot attempted a real model call")):
        return pilot(replace(settings, enabled=False, api_key=""), directory, live_model=False)


if __name__ == "__main__":
    raise SystemExit(main())
