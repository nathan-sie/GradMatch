"""Deterministic transport fixtures. These are NOT model benchmark results."""

import json
from datetime import date
from uuid import uuid4

from gradmatch.agent_models import Action, Extraction
from gradmatch.planning import CRITERION, PlanDraft
from gradmatch.ranking import RankingDraft
from gradmatch.tiers import selectivity_tier

AS_OF = date(2026, 11, 19)


def step(
    name,
    tool,
    depends=(),
    programs=(),
    fields=(),
    source=None,
    requested=(),
    question=None,
):
    return dict(
        step_id=name,
        tool=tool,
        program_ids=list(programs),
        target_fields=list(fields),
        source_id=source,
        depends_on=list(depends),
        status="pending",
        done_criteria=[CRITERION[tool]],
        requested_fields=list(requested),
        question=question,
    )


def plan(prefix=(), programs=(), fields=()):
    """A valid test plan with explicit predecessor dependencies."""
    steps = list(prefix)
    dependency = [steps[-1]["step_id"]] if steps else []
    steps.append(step("check", "check_constraints", dependency, programs, fields))
    steps.append(step("rank", "rank_programs", ["check"], programs))
    steps.append(step("validate", "validate_shortlist", ["rank"]))
    return dict(
        summary="Controlled fixture plan; not a real model decision.", steps=steps
    )


class FixtureProvider:
    def __init__(self, plans=(), extraction=None):
        self.plans = list(plans)
        self.extraction = extraction
        self.calls = []

    def generate(self, kind, purpose, payload, session):
        self.calls.append((purpose, payload))
        session.usage.append(
            dict(
                call_id=str(uuid4()),
                purpose=purpose,
                status="test_stub",
                actual_request=False,
                model="offline-fixture",
                input_tokens=None,
                output_tokens=None,
                cached_input_tokens=None,
                reasoning_tokens=None,
                estimated_cost_usd=None,
                duration_ms=0,
            )
        )
        if purpose == "plan":
            if self.plans:
                value = self.plans.pop(0)
                if callable(value):
                    value = value(payload)
            else:
                prefix = (
                    []
                    if payload["retrieved_program_ids"]
                    else [step("search", "search_programs")]
                )
                value = plan(prefix)
            return PlanDraft.model_validate(value)
        if purpose == "act":
            scope = payload["retrieved_program_ids"]
            if not scope:
                tool, args = "search_programs", {}
            else:
                tool = (
                    "rank_programs"
                    if payload["current_state"]["checks_current"]
                    else "check_constraints"
                )
                args = dict(
                    program_ids=scope,
                    profile_version=session.profile.profile_version,
                    evidence_version=payload["evidence_version"],
                )
            return Action(
                tool=tool,
                arguments_json=json.dumps(args),
                summary="Controlled fixture decision.",
            )
        if purpose == "extract":
            return Extraction.model_validate(self.extraction)
        if purpose == "rank":
            recommendations = []
            for p in payload["programs"]:
                if p["program_id"] not in payload["allowed_recommendation_program_ids"]:
                    continue
                options = next(
                    o
                    for o in payload["ready_recommendation_options"]
                    if o["program_id"] == p["program_id"]
                )
                for evidence in p["admission_evidence"]:
                    # Match the shared validator; do not manufacture a tier from a name.
                    from gradmatch.schemas import AdmissionEvidence

                    tier = selectivity_tier(AdmissionEvidence.model_validate(evidence))
                    if tier and tier in evidence["permitted_tiers"]:
                        recommendations.append(
                            dict(
                                program_id=p["program_id"],
                                tier=tier,
                                goal_feature_ids=options["goal_feature_ids"],
                                tier_evidence_ids=[evidence["evidence_id"]],
                                comparison_dimensions=["selectivity"],
                                lower_risk_rationale=None,
                                limitations=[
                                    "Cohort evidence is not a personal admission probability."
                                ],
                            )
                        )
                        break
            formal = {r["program_id"] for r in recommendations}
            pending = [
                p for p in payload["allowed_pending_program_ids"] if p not in formal
            ]
            return RankingDraft(
                profile_version=session.profile.profile_version,
                status="insufficient_evidence"
                if pending
                else "completed"
                if formal
                else "infeasible",
                recommendations=recommendations,
                pending_order=pending,
                observations=[],
            )
        raise AssertionError(f"Unexpected fixture purpose: {purpose}")
