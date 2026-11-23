"""Run a bounded, paired model pilot for historical admissions evidence."""

import argparse
from dataclasses import replace
from datetime import date
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from gradmatch.admission_history import load_preview
from gradmatch.catalog import current_seed, load_seed
from gradmatch.config import load_settings
from gradmatch.providers import OpenAIProvider
from gradmatch.schemas import GPA
from gradmatch.service import export_session, start_task
from gradmatch.session import Session, tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import blocking_validation_errors, data_hash
from scripts.pilot_broad_recommendations import write_result


CALLS_PER_ARM = 3
AS_OF = date(2026, 11, 22)


def hash_without_history(payload):
    content = {key: value for key, value in payload.items() if key != "admission_history_options"}
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_arm(name, history, settings, dataset, profile, directory, *, fixture=None):
    programs, sources = dataset
    session = Session(profile=profile.model_copy(deep=True))
    rank_inputs = []
    provider_type = type(fixture) if fixture is not None else OpenAIProvider
    provider_generate = provider_type.generate

    def record_rank_input(provider, kind, purpose, payload, current_session):
        if purpose == "rank":
            rank_inputs.append({
                "base_input_hash": hash_without_history(payload),
                "candidate_count": len(payload["allowed_preliminary_program_ids"]),
                "history_options": payload.get("admission_history_options", []),
            })
            write_result(directory / f"{name}_rank_inputs.json", rank_inputs)
        return provider_generate(provider, kind, purpose, payload, current_session)

    def deny_page(*args, **kwargs):
        raise AssertionError("A snapshot pilot cannot fetch external pages.")

    with patch.object(provider_type, "generate", record_rank_input):
        result = start_task(
            session, request_id=str(uuid4()), programs=programs, sources=sources,
            settings=settings, as_of=AS_OF, strategy="plan", data_mode="snapshot",
            recommendation_scope="broad", history_preview=history, fetcher=deny_page, provider=fixture,
        )
    suggestions = result.get("preliminary_recommendations", [])
    references = [item["admission_history_evidence"] for item in suggestions if "admission_history_evidence" in item]
    options = rank_inputs[-1]["history_options"] if rank_inputs else []
    revisions = (result.get("task_usage", {}).get("plan") or {}).get("revisions", [])
    checks = {
        "assessment_validated": result.get("validation_passed", False) and not blocking_validation_errors(result),
        "rank_completed": any(item["purpose"] == "rank" and (
            item["status"] == "test_stub" if fixture is not None
            else item["status"] == "completed" and bool(item.get("response_id"))
        ) for item in session.usage),
        "plan_completed": bool(revisions and revisions[-1]["status"] == "completed"),
        "full_pool_screened": result.get("catalog_program_count") == 83
        and len(set(result.get("retrieved_program_ids", []))) == 83,
        "intended_data_arm": (
            result.get("admission_history_ranking", {}).get("enabled") == (history is not None)
            and (history is not None or not options)
        ),
        "references_resolve": all(reference in options for reference in references),
    }
    summary = {
        "status": result["status"],
        "checks": checks,
        "history_options": len(options),
        "history_option_program_ids": sorted(option["program_id"] for option in options),
        "history_references": references,
        "base_rank_input_hash": rank_inputs[-1]["base_input_hash"] if rank_inputs else None,
        "preliminary_program_ids": [item["program_id"] for item in suggestions],
        "formal_tiers": sorted((item["program_id"], item["tier"]) for item in result.get("recommendations", [])),
        "verified_excluded_program_ids": sorted(item["program_id"] for item in result.get("excluded", [])),
        "model_request_attempts": sum(item.get("actual_request", True) for item in session.usage),
        "service_latency_ms": result["service_latency_ms"],
        "usage": session.usage,
    }
    write_result(directory / f"{name}_session.json", export_session(session))
    write_result(directory / f"{name}_summary.json", summary)
    print(f"{name}: {result['status']}, {summary['model_request_attempts']} model requests, "
          f"{len(options)} options, {len(references)} citations.", flush=True)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live-model", action="store_true", help="Run one pair, capped at six model requests.")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    history = load_preview()
    seed = current_seed()
    dataset = load_seed(seed)
    profile = tiering_profile().model_copy(update={"gpa": GPA(value="3.80", scale="4")})
    if history is None or history.compare(profile) is None:
        parser.error("A compatible aggregate preview is required. Build it with the admission DP audit.")
    print(f"Plan-and-replan A/B on {seed.name} and {len(history.programs)} mapped programs. "
          f"Maximum {CALLS_PER_ARM * 2} requests.", flush=True)
    if not args.live_model:
        return 0
    settings = load_settings()
    if not settings.ready:
        parser.error("An enabled local model configuration is required for this pilot.")
    settings = replace(settings, limits={**settings.limits, "max_model_calls_per_session": CALLS_PER_ARM})
    directory = args.output_dir or PROJECT_ROOT / "work/admissions_dp" / f"real-ab-{uuid4().hex[:12]}"
    directory.mkdir(parents=True, exist_ok=False)
    print(f"Evidence directory: {directory}", flush=True)

    control = run_arm("history_off", None, settings, dataset, profile, directory)
    treatment = run_arm("history_on", history, settings, dataset, profile, directory)
    costs = [item.get("estimated_cost_usd") for arm in (control, treatment) for item in arm["usage"]]
    both_validated = treatment["history_options"] > 0 and all(
        all(arm["checks"].values()) for arm in (control, treatment)
    )
    report = {
        "status": "paired_run_validated" if both_validated else "inconclusive",
        "mode": "real_model",
        "as_of": AS_OF.isoformat(),
        "catalog_seed": seed.name,
        "catalog_hash": data_hash(*dataset),
        "history_snapshot_hash": history.fingerprint(),
        "maximum_model_requests": CALLS_PER_ARM * 2,
        "model_request_attempts": control["model_request_attempts"] + treatment["model_request_attempts"],
        "estimated_model_cost_usd": str(sum(Decimal(cost) for cost in costs)) if costs and all(cost is not None for cost in costs) else None,
        "same_base_rank_input": bool(control["base_rank_input_hash"])
        and control["base_rank_input_hash"] == treatment["base_rank_input_hash"],
        "same_formal_tiers": control["formal_tiers"] == treatment["formal_tiers"],
        "same_verified_exclusions": control["verified_excluded_program_ids"] == treatment["verified_excluded_program_ids"],
        "benchmark_scores": "not_measured",
        "history_off": control,
        "history_on": treatment,
    }
    write_result(directory / "comparison.json", report)
    print(f"{report['status']}: {report['model_request_attempts']} requests. See {directory / 'comparison.json'}", flush=True)
    return int(not both_validated)


if __name__ == "__main__":
    raise SystemExit(main())
