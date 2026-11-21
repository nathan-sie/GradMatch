"""Shared planning-tier evidence checks; cohort selectivity is not a personal prediction."""

from decimal import Decimal

RUBRIC_VERSION = "conservative-v1.1"


def reviewed_cohort_context(program, sources, profile, as_of):
    """Return source-bound program statistics without making an applicant recommendation."""
    from gradmatch.constraints import evidence_ids

    if profile.intake is None:
        return []
    ids = evidence_ids(program, 'admission_evidence', sources, profile)
    if not ids or not any('admission_evidence' in sources[sid].verified_values.get('admission_evidence', {}) for sid in ids):
        return []
    latest = min(as_of.year, profile.intake.year - 1)
    rows = []
    for evidence in program.admission_evidence:
        if (evidence.kind != 'program_selectivity' or not evidence.reviewed
                or evidence.applications is None or evidence.offers is None
                or not evidence.source_ids or not set(evidence.source_ids) <= set(ids)
                or not latest - 2 <= evidence.cycle_year <= latest):
            continue
        label = selectivity_tier(evidence)
        rows.append(dict(
            evidence_id=evidence.evidence_id, cycle_year=evidence.cycle_year,
            applications=evidence.applications, offers=evidence.offers,
            cohort_planning_label=label if label in evidence.permitted_tiers else None,
            source_ids=list(evidence.source_ids),
            scope='Program cohort only; not an applicant admission probability, eligibility result or recommendation',
        ))
    return sorted(rows, key=lambda row: (-row['cycle_year'], row['evidence_id']))


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
