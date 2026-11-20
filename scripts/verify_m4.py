"""Verify M4 offline; real official reads and bounded paid acceptance require explicit flags."""

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from gradmatch.agent import Task
from gradmatch.catalog import load_seed
from gradmatch.config import load_settings
from gradmatch.constraints import check_constraints
from gradmatch.service import start_task, export_session
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import validate_shortlist
from gradmatch.web_reader import read_page, FetchError


def write_new(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(value, indent=2) + "\n")


def live_acceptance(directory, *, paid=False, model_cap=8):
    programs, sources = load_seed()
    page_results = []
    for tag in ["uw_requirements", "mcds_fees"]:
        source = next(s for s in sources.values() if tag in s.source_id)
        program = next(p for p in programs if p.program_id == source.program_id)
        try:
            page = read_page(str(source.url), program.allowed_official_hosts)
            write_new(directory / (tag + ".json"), page.public())
            page_results.append(
                {
                    "status": "read",
                    "source_id": source.source_id,
                    "url": page.url,
                    "retrieved_at": page.retrieved_at,
                    "raw_sha256": page.raw_sha256,
                    "content_type": page.content_type,
                    "characters": len(page.text),
                }
            )
        except FetchError as error:
            page_results.append(
                {"status": "failed", "source_id": source.source_id, "code": error.code}
            )
    result = {
        "official_reads": page_results,
        "model": "not_run",
        "milestone_complete": False,
    }
    if not paid:
        return result
    settings = load_settings()
    if not settings.ready:
        raise ValueError("Configure and enable the existing local model first.")
    # Synthetic controlled missing-field task; never mutate the seed/public database.
    profile = tiering_profile()
    program = next(p for p in programs if p.program_id == "uw-ece-msece-pmp-seattle")
    program.field_sources["credits"] = []
    before = check_constraints(profile, program, sources, as_of=date(2026, 11, 19))
    session = Session(profile=profile)
    session.current_result = validate_shortlist(
        None, profile, programs, programs, sources, as_of=date(2026, 11, 19)
    )
    limits = json.loads((PROJECT_ROOT / "config/agent.json").read_text())
    limits["max_models"] = model_cap
    session.agent_task = Task("react", "live", programs, sources, limits)
    response = start_task(
        session,
        request_id=str(uuid4()),
        programs=programs,
        sources=sources,
        settings=settings,
        as_of=date(2026, 11, 19),
        strategy="react",
        data_mode="live",
        message="For uw-ece-msece-pmp-seattle, fetch only the registered official degree requirements page to verify required credits. Use the existing published-rate tuition snapshot for the cost calculation; do not refresh the tuition page. Check and rank this program with the current profile, retaining any eligibility gaps. Do not change my profile.",
    )
    write_new(directory / "actual_agent_session.json", export_session(session))
    task = session.agent_task
    updated = next(p for p in task.programs if p.program_id == program.program_id)
    after = check_constraints(profile, updated, task.sources, as_of=date(2026, 11, 19))
    cost = next(c for c in after.checks if c.rule_id == "tuition")
    live_ids = [sid for sid in cost.source_ids if sid.startswith("live-")]
    passed = (
        before.tuition.upper_usd is None
        and after.tuition.upper_usd == 50850
        and live_ids
        and session.profile == profile
        and task.pages >= 1
        and response["status"] not in {"error", "budget_exhausted", "needs_input"}
    )
    result.update(
        model="completed" if passed else "failed",
        milestone_complete=bool(passed),
        run_id=response["run_id"],
        task_id=task.task_id,
        status=response["status"],
        model_requests=len(session.usage),
        usage=session.usage,
        tool_calls=task.tools,
        page_requests=task.pages,
        tuition_before=before.tuition.model_dump(mode="json"),
        tuition_after=after.tuition.model_dump(mode="json"),
        source_ids=cost.source_ids,
        live_source_passages=[
            task.sources[sid].model_dump(mode="json") for sid in live_ids
        ],
        action_summaries=[
            e["payload"]["action"]
            for e in session.events
            if e["event_type"] == "agent_action"
        ],
        profile_preserved=session.profile == profile,
        actual_evidence_path=str(directory / "actual_agent_session.json"),
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-pages", action="store_true")
    parser.add_argument(
        "--live-model",
        action="store_true",
        help="Bounded metered requests with fictional data; no retry.",
    )
    parser.add_argument(
        "--max-live-model-calls", type=int, choices=range(1, 17), default=8
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Use only after the current revision passed its offline checks.",
    )
    args = parser.parse_args()
    directory = args.output_dir or PROJECT_ROOT / "work/m4" / str(uuid4())
    directory.mkdir(parents=True, exist_ok=False)
    report = {
        "milestone": "M4",
        "verified_at": datetime.now(timezone.utc).isoformat(),
        "offline": "not_run",
        "live": "not_run",
        "milestone_complete": False,
    }
    if not args.skip_tests:
        check = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        (directory / "offline_tests.txt").write_text(
            check.stdout + check.stderr, encoding="utf-8"
        )
        report["offline"] = "passed" if check.returncode == 0 else "failed"
        print(check.stdout.strip().splitlines()[-1])
        if check.returncode:
            write_new(directory / "verification.json", report)
            return 1
    if args.live_pages or args.live_model:
        report["live"] = live_acceptance(
            directory, paid=args.live_model, model_cap=args.max_live_model_calls
        )
        report["milestone_complete"] = report["live"]["milestone_complete"]
    write_new(directory / "verification.json", report)
    print(
        json.dumps(
            {
                "offline": report["offline"],
                "live_model": report["live"].get("model")
                if isinstance(report["live"], dict)
                else "not_run",
                "milestone_complete": report["milestone_complete"],
                "report": str(directory / "verification.json"),
            },
            indent=2,
        )
    )
    return 0 if not args.live_model or report["milestone_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
