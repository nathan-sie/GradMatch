"""Shared structured ranking contract and stable fixed top-k retrieval."""

from typing import Literal

from gradmatch.schemas import Record


Tier = Literal["Lottery", "Reach", "Target", "Safer"]
TIERS = ["Lottery", "Reach", "Target", "Safer"]


class RecommendationDraft(Record):
    program_id: str
    tier: Tier
    goal_feature_ids: list[str]
    tier_evidence_ids: list[str]
    comparison_dimensions: list[Literal["gpa", "major", "research", "work_experience", "selectivity"]]
    lower_risk_rationale: str | None
    limitations: list[str]


class Observation(Record):
    program_id: str
    rule_id: str
    source_ids: list[str]


class RankingDraft(Record):
    profile_version: int
    status: Literal["completed", "insufficient_evidence", "infeasible"]
    recommendations: list[RecommendationDraft]
    pending_order: list[str]
    observations: list[Observation]


def retrieve(profile, programs, top_k):
    # No embedding/model lookup. All three later strategies can use this same catalog.
    major = (profile.major or "").lower()
    def score(program):
        discipline_match = (program.discipline == "ECE" and any(s in major for s in ["electrical", "ece", "electronic"])) or (
            program.discipline == "CS" and any(s in major for s in ["computer science", "software"]))
        goal_match = any(feature.goal in {profile.goal, "mixed"} for feature in program.goal_features)
        return (-int(discipline_match), -int(goal_match), program.program_id)
    return sorted(programs, key=score)[:top_k]
