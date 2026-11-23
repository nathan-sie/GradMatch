"""Evaluate paired DP runs against a frozen local pilot and prepare blind review."""

import argparse
from dataclasses import replace
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import random
import socket
from unittest.mock import patch
from uuid import uuid4

from gradmatch.admission_history import load_preview
from gradmatch.broad_catalog import build_broad_catalog
from gradmatch.catalog import load_seed
from gradmatch.config import ModelSettings, load_settings
from gradmatch.providers import OpenAIProvider
from gradmatch.ranking import PreliminaryRecommendationDraft
from gradmatch.schemas import ApplicantProfile
from gradmatch.session import tiering_profile
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import data_hash
from scripts.pilot_broad_recommendations import write_result
from scripts.pilot_history_ranking import AS_OF, CALLS_PER_ARM, run_arm
from scripts.verify_broad_recommendations import BroadFixture


SUITE = PROJECT_ROOT / "eval/dp_pilot.json"
REVIEW_CRITERIA = {
    "goal_fit": "Do the top five suggestions match the applicant's academic preparation and stated goal?",
    "constraint_handling": "Do the suggestions respect known constraints and make unresolved checks visible?",
    "actionability": "Do the suggested programs and evidence-backed reasons support a concrete application decision?",
}


class HistoryFixture(BroadFixture):
    """Exercise citation validation with controlled selections."""

    def generate(self, kind, purpose, payload, session):
        draft = super().generate(kind, purpose, payload, session)
        if purpose == "rank":
            formal = {row.program_id for row in draft.recommendations}
            options = [row for row in payload.get("admission_history_options", []) if row["program_id"] not in formal]
            cited = [
                PreliminaryRecommendationDraft(program_id=row["program_id"], reason_check_ids=["application_info"],
                                               history_evidence_id=row["evidence_id"])
                for row in options[:2]
            ]
            remaining = [row for row in draft.suggestions if row.program_id not in {item.program_id for item in cited}]
            draft.suggestions = (cited + remaining)[:8]
        return draft


def read_json(path):
    return json.loads(path.read_bytes())


def load_pilot():
    suite = read_json(SUITE)
    dataset = load_seed(PROJECT_ROOT / suite["catalog_seed"])
    history = load_preview()
    _, broad = build_broad_catalog(*dataset)
    if (suite["as_of"] != AS_OF.isoformat() or data_hash(*dataset) != suite["catalog_hash"]
            or broad["data_hash"] != suite["community_hash"]):
        raise ValueError("The evaluation date or catalog has changed since the DP suite was authored.")
    if history is None or history.fingerprint() != suite["history_snapshot_hash"]:
        raise ValueError("The DP suite requires the pinned local history preview. See ADMISSION_DP_PILOT.md.")
    return suite, dataset, history


def profile_for(case):
    base = tiering_profile().model_dump(mode="json")
    profile = {**base, **case["profile"]}
    profile["degree"] = {**base["degree"], **case["profile"].get("degree", {})}
    return ApplicantProfile.model_validate(profile)


def grade_pair(case, off, on):
    expected_exclusions = set(case.get("expected_budget_exclusions", []))
    excluded = [set(arm["verified_excluded_program_ids"]) for arm in (off, on)]
    checks = {
        "both_assessments_complete": all(all(arm["checks"].values()) for arm in (off, on)),
        "matching_base_rank_inputs": bool(off["base_rank_input_hash"])
        and off["base_rank_input_hash"] == on["base_rank_input_hash"],
        "expected_history_options": off["history_options"] == 0
        and on["history_options"] == case["expected_history_options"],
        "matching_verified_exclusions": excluded[0] == excluded[1],
        "known_budget_exclusions": all(expected_exclusions <= ids for ids in excluded),
        "exclusions_respected": all(
            ids.isdisjoint(arm["preliminary_program_ids"])
            and ids.isdisjoint(pid for pid, _ in arm["formal_tiers"])
            and ids.isdisjoint(arm["history_option_program_ids"])
            for ids, arm in zip(excluded, (off, on))
        ),
    }
    return {"passed": all(checks.values()), "checks": checks,
            "same_formal_tiers": off["formal_tiers"] == on["formal_tiers"]}


def review_arm(directory, arm):
    result = read_json(directory / f"{arm}_session.json").get("result") or {}
    return {
        "suggestions": [
            {
                **{key: item[key] for key in ("identity", "reasons", "limitations")},
                "check_statuses": {check["rule_id"]: check["status"] for check in item["checks"]["checks"]},
            }
            for item in result.get("preliminary_recommendations", [])[:5]
        ],
        "scores": dict.fromkeys(REVIEW_CRITERIA),
        "notes": "",
    }


def run_pilot(args, suite, dataset, history, profiles):
    raw_settings = load_settings() if args.live_model else ModelSettings(
        "fixture", "offline-fixture", False, "", read_json(PROJECT_ROOT / "config/app.json"),
    )
    if args.live_model and not raw_settings.ready:
        raise ValueError("An enabled local model configuration is required.")
    settings = replace(raw_settings, limits={**raw_settings.limits, "max_model_calls_per_session": CALLS_PER_ARM})
    root = args.output_dir or PROJECT_ROOT / "work/admissions_dp" / f"batch-{uuid4().hex[:12]}"
    root.mkdir(parents=True, exist_ok=False)
    print(f"Evidence directory: {root}", flush=True)
    report = {"suite_version": suite["version"], "suite_sha256": hashlib.sha256(SUITE.read_bytes()).hexdigest(),
              "catalog_hash": suite["catalog_hash"], "model": settings.model,
              "community_hash": suite["community_hash"], "history_snapshot_hash": suite["history_snapshot_hash"],
              "as_of": suite["as_of"], "mode": "real_model" if args.live_model else "offline_fixture", "cases": []}
    packet = {"instruction": "Independently rate each shortlist from 0 (poor) to 2 (strong) on each criterion. Cite a concrete example in the notes.",
              "criteria": REVIEW_CRITERIA, "cases": []}
    rng = random.Random(20261122)
    costs = []
    for index, (case, profile) in enumerate(zip(suite["cases"], profiles)):
        case_id = case["id"]
        directory = root / case_id
        directory.mkdir()
        options = {"history_off": None, "history_on": history}
        arm_order = list(options) if index % 2 == 0 else list(reversed(options))
        results = {
            arm: run_arm(arm, options[arm], settings, dataset, profile, directory,
                         fixture=None if args.live_model else HistoryFixture())
            for arm in arm_order
        }
        off, on = results["history_off"], results["history_on"]
        costs.extend(item.get("estimated_cost_usd") for arm in results.values() for item in arm["usage"])
        grade = grade_pair(case, off, on)
        blind_mapping = dict(zip(("A", "B"), rng.sample(arm_order, k=2)))
        report["cases"].append({
            "id": case_id, "grade": grade, "arm_order": arm_order, "review_key": blind_mapping,
            "offered_options": on["history_options"], "verified_citations": len(on["history_references"]),
            "model_request_attempts": sum(arm["model_request_attempts"] for arm in results.values()),
        })
        if grade["passed"]:
            packet["cases"].append({
                "id": case_id, "profile": profile.model_dump(mode="json"),
                "shortlists": {label: review_arm(directory, arm) for label, arm in blind_mapping.items()},
            })

    report["passed_pairs"] = sum(case["grade"]["passed"] for case in report["cases"])
    report["model_request_attempts"] = sum(case["model_request_attempts"] for case in report["cases"])
    report["estimated_model_cost_usd"] = (
        str(sum(Decimal(cost) for cost in costs)) if costs and all(cost is not None for cost in costs) else None
    ) if args.live_model else "0"
    report["quality_review"] = "pending_review" if args.live_model else "fixture_only"
    write_result(root / "comparison.json", report)
    write_result(root / "blind_review.json", packet)
    print(f"{report['passed_pairs']}/{len(profiles)} pairs passed. "
          f"Model requests: {report['model_request_attempts']}. Results: {root / 'comparison.json'}")
    return int(report["passed_pairs"] != len(profiles))


def deny_network(*args, **kwargs):
    raise AssertionError("Offline DP fixtures cannot access the network.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--fixtures", action="store_true", help="Run the suite with local fixtures and zero paid calls.")
    mode.add_argument("--live-model", action="store_true", help="Run the frozen suite with real model calls.")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    try:
        suite, dataset, history = load_pilot()
        profiles = [profile_for(case) for case in suite["cases"]]
        print(f"{len(profiles)} paired cases. Maximum {len(profiles) * 2 * CALLS_PER_ARM} requests in live mode.",
              flush=True)
        if args.live_model:
            return run_pilot(args, suite, dataset, history, profiles)
        if args.fixtures:
            with (patch.object(OpenAIProvider, "generate", deny_network),
                  patch.object(socket, "getaddrinfo", deny_network),
                  patch.object(socket.socket, "connect", deny_network)):
                return run_pilot(args, suite, dataset, history, profiles)
        return 0
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
