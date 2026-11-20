"""Recompute facts and reject unsupported rankings before anything is displayed."""

from collections import Counter
from datetime import date
import hashlib
import json

from gradmatch.constraints import check_constraints, evidence_ids
from gradmatch.ranking import TIERS, RankingDraft
from gradmatch.tiers import RUBRIC_VERSION, planning_reason, selectivity_tier


def blocking_validation_errors(result):
    """Code-owned status normalization needs no new model decision.

    Keep the legacy findings list intact for audits. Every factual, scope,
    version, eligibility, tier or citation rejection remains blocking.
    """
    return [e for e in result.get('validation_errors', [])
            if e.get('code') != 'MODEL_STATUS_CORRECTED']


def data_hash(programs, sources):
    value = {"programs": [p.model_dump(mode="json") for p in sorted(programs, key=lambda p: p.program_id)],
        "sources": [s.model_dump(mode="json") for s in sorted(sources.values(), key=lambda s: s.source_id)]}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def tier_errors(item, profile, program, sources, as_of):
    errors = []
    features = {f.feature_id: f for f in program.goal_features}
    goal_ids = evidence_ids(program, "goal_features", sources, profile)
    if not any("goal_features" in sources[sid].verified_values.get("goal_features", {}) for sid in goal_ids):
        goal_ids = []
    if not item.goal_feature_ids or len(item.goal_feature_ids) != len(set(item.goal_feature_ids)):
        errors.append("MISSING_OR_DUPLICATE_GOAL_EVIDENCE")
    for feature_id in item.goal_feature_ids:
        feature = features.get(feature_id)
        if (feature is None or feature.goal not in {profile.goal, "mixed"}
            or not feature.source_ids or not set(feature.source_ids) <= set(goal_ids)):
            errors.append("UNSUPPORTED_GOAL_FIT")
    admissions = {e.evidence_id: e for e in program.admission_evidence}
    admission_ids = evidence_ids(program, "admission_evidence", sources, profile)
    if not any("admission_evidence" in sources[sid].verified_values.get("admission_evidence", {}) for sid in admission_ids):
        admission_ids = []
    used = []
    latest_cycle = min(as_of.year, profile.intake.year - 1) if profile.intake else as_of.year - 1
    for evidence_id in item.tier_evidence_ids:
        evidence = admissions.get(evidence_id)
        if (evidence is None or not evidence.reviewed or not evidence.source_ids
                or not set(evidence.source_ids) <= set(admission_ids)
                or not latest_cycle - 2 <= evidence.cycle_year <= latest_cycle
                or item.tier not in evidence.permitted_tiers):
            errors.append("UNSUPPORTED_TIER_EVIDENCE")
            continue
        used.append(evidence)
        if evidence.kind == "program_selectivity" and (
                selectivity_tier(evidence) != item.tier or "selectivity" not in item.comparison_dimensions):
            errors.append("COHORT_DOES_NOT_SUPPORT_REQUESTED_TIER")
    if not used or len(item.tier_evidence_ids) != len(set(item.tier_evidence_ids)):
        errors.append("MISSING_OR_DUPLICATE_TIER_EVIDENCE")
    if not item.limitations or not item.comparison_dimensions:
        errors.append("MISSING_COMPARISON_OR_LIMITATIONS")
    if item.tier in {"Target", "Safer"}:
        comparable = [e for e in used if e.kind == "admitted_case" and e.gpa and profile.gpa
            and e.gpa.scale == profile.gpa.scale and e.gpa.scope == profile.gpa.scope
            and e.major and profile.major and e.experience_dimensions
            and any(getattr(profile, dimension) for dimension in e.experience_dimensions)]
        if (len({e.independence_key for e in comparable}) < 2 or "gpa" not in item.comparison_dimensions
                or not set(item.comparison_dimensions) & {"research", "work_experience"}):
            errors.append("INSUFFICIENT_COMPARABLE_CASES")
    if item.tier == "Safer" and not item.lower_risk_rationale:
        errors.append("MISSING_LOWER_RISK_RATIONALE")
    # Free text is a limitation/rationale, never used to authorize a hard-check pass.
    return errors


def validate_shortlist(draft: RankingDraft | None, profile, all_programs, retrieved, sources, *, as_of: date, data_mode="snapshot"):
    by_id = {program.program_id: program for program in retrieved}
    reports = {p.program_id: check_constraints(profile, p, sources, as_of=as_of,data_mode=data_mode) for p in retrieved}
    errors, accepted, observations = [], [], []
    counts = Counter()
    seen = set()
    if draft is not None and draft.profile_version != profile.profile_version:
        errors.append({"code": "STALE_PROFILE_VERSION"})
        draft = None
    for item in draft.recommendations if draft else []:
        codes = []
        program = by_id.get(item.program_id)
        if item.program_id in seen:
            codes.append("DUPLICATE_PROGRAM")
        seen.add(item.program_id)
        if program is None:
            codes.append("PROGRAM_NOT_RETRIEVED")
        else:
            if not reports[item.program_id].recommendation_ready:
                codes.append("HARD_CHECKS_NOT_PASSED")
            codes.extend(tier_errors(item, profile, program, sources, as_of))
        if counts[item.tier] >= 5:
            codes.append("TIER_LIMIT_EXCEEDED")
        if codes:
            errors.append({"program_id": item.program_id, "codes": sorted(set(codes))})
            continue
        counts[item.tier] += 1
        # Names, URLs, dates, amounts and quotes come from the catalog, never model memory.
        source_ids = sorted({sid for f in program.goal_features if f.feature_id in item.goal_feature_ids for sid in f.source_ids}
            | {sid for e in program.admission_evidence if e.evidence_id in item.tier_evidence_ids for sid in e.source_ids})
        accepted.append({**item.model_dump(mode="json"), "identity": identity(program),
            "planning_reason": planning_reason(item, program),
            "application_materials": list(program.application_materials),
            "checks": reports[item.program_id].model_dump(mode="json"),
            "goal_features": [f.model_dump(mode="json") for f in program.goal_features if f.feature_id in item.goal_feature_ids],
            "tier_evidence": [e.model_dump(mode="json") for e in program.admission_evidence if e.evidence_id in item.tier_evidence_ids],
            "citations": [citation(sources[sid]) for sid in source_ids]})
    accepted_ids = {item["program_id"] for item in accepted}
    pending, excluded = [], []
    for program in retrieved:
        report = reports[program.program_id]
        failed = [c for c in report.checks if c.status == "fail"]
        if failed:
            excluded.append({"program_id": program.program_id, "identity": identity(program),
                "reason_codes": [c.reason_code for c in failed], "reasons": [c.explanation for c in failed]})
        elif program.program_id not in accepted_ids:
            missing = [c.rule_id for c in report.checks if c.status == "unknown"]
            if not program.goal_features: missing.append("goal_features")
            if not program.admission_evidence: missing.append("admission_tier_evidence")
            if not missing: missing.append("validated_ranking")
            pending.append({"program_id": program.program_id, "identity": identity(program),
                "missing_fields": missing, "report": report.model_dump(mode="json")})
    if draft:
        pending_ids = {item["program_id"] for item in pending}
        for pid in draft.pending_order:
            if pid not in pending_ids:
                errors.append({"program_id": pid, "code": "INVALID_PENDING_REFERENCE"})
        order = {pid: i for i, pid in enumerate(dict.fromkeys(draft.pending_order)) if pid in pending_ids}
        pending.sort(key=lambda item: (order.get(item["program_id"], len(order)), item["program_id"]))
        for item in draft.observations:
            report = reports.get(item.program_id)
            check = next((c for c in report.checks if c.rule_id == item.rule_id), None) if report else None
            if check is None or not set(item.source_ids) <= set(check.source_ids) or len(set(item.source_ids)) != len(item.source_ids):
                errors.append({"program_id": item.program_id, "code": "UNSUPPORTED_OBSERVATION_CITATION"})
            else:
                observations.append({"program_id": item.program_id, "rule_id": check.rule_id,
                    "status": check.status.value, "explanation": check.explanation,
                    "citations": [citation(sources[sid]) for sid in check.source_ids]})
    all_retrieved = set(by_id) == {p.program_id for p in all_programs} and bool(all_programs)
    infeasible = all_retrieved and len(excluded) == len(all_programs)
    status = "infeasible" if infeasible else "completed" if accepted and not pending and not errors else "insufficient_evidence"
    if draft and draft.status != status:
        errors.append({"code": "MODEL_STATUS_CORRECTED", "proposed": draft.status, "verified": status})
    return {"status": status, "profile_version": profile.profile_version, "as_of_date": str(as_of),
        "data_mode": data_mode, "data_hash": data_hash(all_programs, sources),
        "recommendations": accepted, "pending_verification": pending, "excluded": excluded,
        "observations": observations, "validation_errors": errors,
        "validation_warnings": [e for e in errors if e.get('code') == 'MODEL_STATUS_CORRECTED'],
        "validation_passed": not blocking_validation_errors({'validation_errors': errors}),
        "tier_shortfalls": [{"tier": tier, "count": counts[tier], "shortfall_to_three": max(0, 3 - counts[tier]),
            "reason": "Insufficient verified eligibility, goal-fit, admission-tier evidence, or validated model ranking."}
            for tier in TIERS if counts[tier] < 3],
        "retrieved_program_ids": list(by_id), "catalog_program_count": len(all_programs),
        "all_catalog_retrieved": all_retrieved,
        "rubric_version": RUBRIC_VERSION}


def identity(program):
    return {"university": program.university, "program_name": program.program_name, "degree": program.degree,
        "campus": program.campus, "track": program.track, "official_url": str(program.official_url)}


def citation(source):
    return {"source_id": source.source_id, "url": str(source.url), "retrieved_at": source.retrieved_at.isoformat(),
        "applicable_intake": source.applicable_intake, "quote": source.source_excerpt, "locator": source.locator}


def changes_from_previous(previous, current):
    def selected(result):
        return {i["program_id"] for field in ["recommendations", "pending_verification"] for i in (result or {}).get(field, [])}
    before, after = selected(previous), selected(current)
    excluded = {i["program_id"]: i for i in current["excluded"]}
    return {"added": sorted(after - before), "retained": sorted(after & before),
        "removed": [{"program_id": pid, "reasons": excluded[pid]["reasons"] if pid in excluded
                     else ["The candidate is no longer in the fixed retrieval set or validated output."]}
                    for pid in sorted(before - after)],
        "previous_profile_version": (previous or {}).get("profile_version")}
