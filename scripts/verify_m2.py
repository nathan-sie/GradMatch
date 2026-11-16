"""Separate offline regression from optional real OpenAI integration. Never fabricate live results."""

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from gradmatch.catalog import load_seed, read_catalog
from gradmatch.config import load_settings
from gradmatch.schemas import ApplicantProfile
from gradmatch.service import export_session, start_task
from gradmatch.session import Session, synthetic_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import data_hash


def live_check(settings, programs, sources, *, resume_record=None, resumed_from=None):
    if not settings.ready:
        return {"status": "not_run", "reason": "Configure the local OpenAI API key and MODEL_ENABLED=true first.", "model_calls": 0}
    if resume_record:
        first = resume_record["turns"][1]
        if (first.get("model_status") != "completed" or first.get("validation_errors")
                or first.get("data_hash") != data_hash(programs, sources)
                or first.get("model_config", {}).get("config_hash") != settings.public()["config_hash"]):
            return {"status": "failed", "reason": "The previous initial response is not valid for this model/configuration/catalog."}
        previous = resume_record["session"]
        session = Session(session_id=previous["session_id"],
            profile=ApplicantProfile.model_validate(first["profile_summary"]),
            current_result=first, usage=list(previous["usage"]), events=list(previous["events"]),
            messages=list(previous["messages"]))
        session.event("acceptance_resumed_after_code_fix", preserved_failed_attempt=resumed_from,
            reused_initial_run_id=first["run_id"])
        missing = resume_record["turns"][0]
        if len(session.usage) + 3 > 6:
            return {"status": "failed", "reason": "Resuming would exceed the six-call acceptance budget. No new request was sent.", "model_calls": len(session.usage)}
    else:
        session = Session()
    def run(**kwargs):
        return start_task(session, request_id=str(uuid4()), programs=programs, sources=sources,
            settings=settings, as_of=date(2026, 11, 15), **kwargs)
    if not resume_record:
        missing = run()
        if missing["status"] != "needs_input" or session.usage:
            return {"status": "failed", "reason": "Missing-information gate did not precede the model."}
        session.update(synthetic_profile().model_dump(exclude={"profile_version"}))
        first = run()
    if first.get("model_status") != "completed":
        return {"status": "failed", "reason": first.get("message", "Initial model request did not complete."), "usage": session.usage}
    original = session.profile.model_dump(mode="json")
    second = run(message="Change my tuition budget to 50000")
    preserved = all(session.profile.model_dump(mode="json")[key] == value
        for key, value in original.items() if key not in {"tuition_budget_usd", "profile_version"})
    third = run(message="Which remaining candidates fit employment goals? Do not change my profile.") if second.get("model_status") == "completed" else None
    expected = second.get("status") == "insufficient_evidence" and not second.get("recommendations")
    removed_uw = any(item["program_id"].startswith("uw-") for item in second.get("changes_from_previous", {}).get("removed", []))
    all_live = all(r and r.get("model_status") == "completed" for r in [first, second, third])
    checks = {"real_model_completed_all_three_turns": all_live, "unchanged_background_preserved": preserved,
        "followup_preserved_profile": bool(third and second.get("profile_summary") == third.get("profile_summary")),
        "budget_is_50000": str(session.profile.tuition_budget_usd) == "50000", "uw_removed_with_reason": removed_uw,
        "honest_insufficient_evidence": expected, "no_unaccepted_model_output": all(not r.get("validation_errors") for r in [first, second, third] if r),
        "bounded_model_calls": len(session.usage) <= 6}
    path = PROJECT_ROOT / "work" / "m2_live_synthetic_session.json"
    path.write_text(json.dumps({"synthetic_only": True, "resumed_from": resumed_from, "session": export_session(session),
        "turns": [missing, first, second, third], "checks": checks}, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"status": "passed" if all(checks.values()) else "failed", "checks": checks,
        "model_calls": len(session.usage), "usage": session.usage, "synthetic_log": str(path),
        "resumed_from": resumed_from, "initial_response_reused": bool(resume_record)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-model", action="store_true", help="Run at most 6 paid requests using only synthetic input.")
    parser.add_argument("--resume-live", type=Path, help="Continue from an archived synthetic attempt, reusing only its validated initial response; all prior calls count toward six.")
    parser.add_argument("--report", type=Path, default=PROJECT_ROOT / "work" / "m2_verification.json")
    args = parser.parse_args()
    report = {"milestone": "M2", "verified_at": datetime.now(timezone.utc).isoformat(),
        "offline_status": "failed", "live_model": {"status": "not_run", "model_calls": 0},
        "manual_acceptance": "pending", "milestone_complete": False, "formal_benchmark": "not_run",
        "data_mode": "snapshot", "official_page_requests": 0, "search_api_calls": 0}
    exit_code = 1
    try:
        expected, expected_sources = load_seed()
        programs, sources = read_catalog()
        if data_hash(programs, sources) != data_hash(expected, expected_sources):
            raise ValueError("The read-only database differs from the validated seed snapshots. Rebuild/import before verification.")
        result = subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=PROJECT_ROOT,
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        print(result.stdout)
        if result.stderr: print(result.stderr, file=sys.stderr)
        report.update(offline_status="passed" if result.returncode == 0 else "failed", test_output=result.stdout,
            data_hash=data_hash(programs, sources), programs=len(programs), official_sources=len(sources),
            model_config=load_settings().public())
        exit_code = result.returncode
        if (args.live_model or args.resume_live) and result.returncode == 0:
            previous = json.loads(args.resume_live.read_text(encoding="utf-8")) if args.resume_live else None
            report["live_model"] = live_check(load_settings(), programs, sources,
                resume_record=previous, resumed_from=str(args.resume_live.resolve()) if args.resume_live else None)
            exit_code = 0 if report["live_model"]["status"] == "passed" else 1
        report["checkpoint"] = ("Automated and real-model checks passed; user page acceptance pending."
            if report["live_model"]["status"] == "passed" else "Offline checks only; real-model and user page acceptance remain pending.")
    except (ValueError, OSError, RuntimeError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
        print(str(error), file=sys.stderr)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"M2 offline: {report['offline_status']}; real model: {report['live_model']['status']}; report: {args.report.resolve()}")
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
