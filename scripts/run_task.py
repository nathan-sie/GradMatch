"""Run the same fixed baseline as the UI. Paid requests require --live-model and local opt-in."""

import argparse
from dataclasses import replace
from datetime import date,datetime
import json
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from gradmatch.catalog import read_catalog
from gradmatch.config import load_settings
from gradmatch.schemas import ApplicantProfile
from gradmatch.service import export_session, start_task
from gradmatch.session import Session, synthetic_profile
from gradmatch.storage import PROJECT_ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--synthetic", action="store_true", help="Use the documented fictional applicant.")
    inputs.add_argument("--profile", type=Path, help="ApplicantProfile JSON; sent to OpenAI only with explicit live opt-in.")
    parser.add_argument("--message")
    parser.add_argument("--followup", action="append", default=[], help="Additional message in the same session.")
    parser.add_argument("--live-model", action="store_true", help="Allow bounded, paid API requests.")
    parser.add_argument('--strategy',choices=['fixed','react'],default='fixed')
    parser.add_argument('--data-mode',choices=['snapshot','live'],default='snapshot')
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(ZoneInfo('America/Los_Angeles')).date())
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "work" / "m2_task.json")
    args = parser.parse_args()
    config = load_settings()
    if args.live_model and not config.ready:
        parser.error("Live model calls require a local API key and MODEL_ENABLED=true. No request was sent.")
    if not args.live_model:
        config = replace(config, enabled=False)
    applicant = synthetic_profile() if args.synthetic else ApplicantProfile.model_validate_json(args.profile.read_text(encoding="utf-8"))
    session = Session(profile=applicant)
    programs, sources = read_catalog()
    results = []
    for message in [args.message, *args.followup]:
        result = start_task(session, request_id=str(uuid4()), programs=programs, sources=sources,
            settings=config, as_of=args.as_of, message=message,strategy=args.strategy,data_mode=args.data_mode)
        results.append(result)
        print(f"{result['status']} | profile v{result['profile_version']} | model {result['model_status']} | calls {result['model_calls']}")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"session": export_session(session), "turns": results}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved: {args.output.resolve()}")
    raise SystemExit(1 if any(r["status"] in {"error","budget_exhausted","stopped"} for r in results) else 0)


if __name__ == "__main__":
    main()
