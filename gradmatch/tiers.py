"""Shared planning-tier evidence checks; cohort selectivity is not a personal prediction."""

from decimal import Decimal

RUBRIC_VERSION = "conservative-v1.1"


def selectivity_tier(evidence):
    if (evidence.kind != "program_selectivity" or evidence.applications is None
            or evidence.offers is None or not evidence.reviewed):
        return None
    rate = Decimal(evidence.offers) / Decimal(evidence.applications)
    if rate <= Decimal("0.15"):
        return "Lottery"
    if rate <= Decimal("0.35"):
        return "Reach"
    return None


def planning_reason(item, program):
    selected = [e for e in program.admission_evidence if e.evidence_id in item.tier_evidence_ids]
    cohorts = [e for e in selected if e.kind == "program_selectivity"]
    if cohorts:
        return " ".join(f"The official {e.cycle_year} program cohort reported {e.offers} offers from {e.applications} applications."
            for e in cohorts) + f" {item.tier} is a cohort-selectivity planning label under {RUBRIC_VERSION}, not your admission probability."
    return f"{item.tier} uses the reviewed comparable cases cited below; individual outcomes remain uncertain."
