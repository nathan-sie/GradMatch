"""Offline evidence coverage and candidate screening; never promotes a lead."""

from collections import Counter
from urllib.parse import urlsplit

from gradmatch.constraints import check_constraints, evidence_ids
from gradmatch.ranking import TIERS, RecommendationDraft
from gradmatch.session import tiering_profile
from gradmatch.validation import data_hash, tier_errors

GROUPS = (
    "identity",
    "intake",
    "gpa",
    "english",
    "english_minimum",
    "prerequisites",
    "degree",
    "gre",
    "credits",
    "tuition",
    "deadline",
    "remaining_eligibility",
    "goal_features",
    "admission_evidence",
)
COMPARISON_ISSUES = {
    "GPA_SCOPE_MISMATCH",
    "GPA_SCALE_MISMATCH",
    "GPA_EXCEPTION_REQUIRES_REVIEW",
    "MISSING_GPA",
    "MISSING_ENGLISH",
    "MISSING_ENGLISH_TEST_DATE",
    "ENGLISH_SUBSCORES_MISSING",
    "COURSEWORK_NOT_PROVIDED",
    "MISSING_DEGREE_BACKGROUND",
    "MISSING_DEGREE_FIELD",
    "MISSING_REQUIRED_GRE",
    "MISSING_BUDGET",
}


def program_audit(program, sources, profile, as_of):
    report = check_constraints(profile, program, sources, as_of=as_of)
    bound = {g: evidence_ids(program, g, sources, profile) for g in GROUPS}
    usable = {g: bool(ids) for g, ids in bound.items()}
    target = profile.intake.key
    usable["intake"] &= target in {
        i.key for i in program.supported_intakes + program.closed_intakes
    }
    usable["gpa"] &= program.gpa is not None and (
        program.gpa.no_hard_minimum or (program.gpa.minimum is not None and bool(program.gpa.accepted_scopes))
    )
    usable["english"] &= program.english_not_required or bool(program.english)
    usable["prerequisites"] &= program.prerequisites_complete
    usable["gre"] &= program.gre_policy != "unknown"
    usable["credits"] &= program.required_credits is not None
    usable["tuition"] = report.tuition.upper_usd is not None
    usable["deadline"] &= bool([r for r in program.deadlines if r.intake.key == target])
    usable["remaining_eligibility"] &= (
        program.eligibility_review_complete
        and bool(bound["degree"])
        and bool(bound["gre"])
    )
    usable["goal_features"] &= bool(program.goal_features)
    latest = min(as_of.year, profile.intake.year - 1)
    admissions = [
        e
        for e in program.admission_evidence
        if e.reviewed
        and e.source_ids
        and set(e.source_ids) <= set(bound["admission_evidence"])
        and latest - 2 <= e.cycle_year <= latest
    ]
    usable["admission_evidence"] &= bool(admissions)
    goal_ids = [
        f.feature_id for f in program.goal_features if f.goal in {profile.goal, "mixed"}
    ]
    potential = []
    for tier in TIERS:
        evidence = [e for e in admissions if tier in e.permitted_tiers]
        item = RecommendationDraft(
            program_id=program.program_id,
            tier=tier,
            goal_feature_ids=goal_ids,
            tier_evidence_ids=[e.evidence_id for e in evidence],
            comparison_dimensions=["selectivity"]
            if any(e.kind == "program_selectivity" for e in evidence)
            else ["gpa"],
            lower_risk_rationale=None,
            limitations=[
                "Reference scenario only; this is not an admission probability."
            ],
        )
        if evidence and not tier_errors(item, profile, program, sources, as_of):
            potential.append(tier)
    gaps = [g for g in GROUPS if g != 'english_minimum' and not usable[g]]
    required_gaps = [
        g for g in gaps if g != "credits" or program.tuition.basis == "per_credit"
    ]
    comparison = [
        c.model_dump(mode="json")
        for c in report.checks
        if c.status == "unknown" and c.reason_code in COMPARISON_ISSUES
    ]
    priority = (
        1
        if potential and not report.recommendation_ready
        else 2
        if not usable["tuition"]
        else 3
    )
    if not required_gaps:
        priority = None
    return dict(
        program_id=program.program_id,
        university=program.university,
        program_name=program.program_name,
        degree=program.degree,
        campus=program.campus,
        track=program.track,
        discipline=program.discipline,
        official_url=str(program.official_url),
        original_candidate_source_id=program.candidate_source_id,
        source_count=sum(s.program_id == program.program_id for s in sources.values()),
        field_coverage={
            g: dict(
                evidence_bound=bool(bound[g]),
                rule_usable=bool(usable[g]),
                source_ids=bound[g],
            )
            for g in GROUPS
        },
        catalog_gaps=gaps,
        next_required_reviews=required_gaps,
        reference_profile_comparison_issues=comparison,
        reference_hard_status=report.hard_checks_status.value,
        reference_unknown_checks=[
            c.model_dump(mode="json") for c in report.checks if c.status == "unknown"
        ],
        reference_failed_checks=[
            c.model_dump(mode="json") for c in report.checks if c.status == "fail"
        ],
        reference_hard_checks_ready=report.recommendation_ready,
        reference_supported_tiers=potential,
        reference_formal_evidence_ready=report.recommendation_ready and bool(potential),
        reviewed_recent_cohorts=sum(
            e.kind == "program_selectivity" for e in admissions
        ),
        reviewed_recent_admitted_cases=sum(
            e.kind == "admitted_case" for e in admissions
        ),
        tuition=report.tuition.model_dump(mode="json"),
        tuition_basis=program.tuition.basis,
        deadline_schedule_complete=program.deadline_schedule_complete,
        gpa_recommendation_only=bool(
            bound["gpa"]
            and program.gpa
            and program.gpa.minimum is None
            and not program.gpa.no_hard_minimum
        ),
        repair_priority=priority,
    )


def audit_catalog(programs, sources, *, as_of, intake):
    profile = tiering_profile()
    profile.intake = intake
    rows = [
        program_audit(p, sources, profile, as_of)
        for p in sorted(programs, key=lambda p: p.program_id)
    ]
    return dict(
        schema_version="m61-catalog-audit-v1",
        as_of_date=str(as_of),
        target_intake=intake.key,
        data_hash=data_hash(programs, sources),
        data_mode="snapshot",
        model_requests=0,
        network_requests=0,
        reference_scenario=dict(
            name="fictional_tiering_profile",
            profile=profile.model_dump(mode="json"),
            notice="Fixed test profile, not a real applicant. Scenario readiness is not universal eligibility or a benchmark score.",
        ),
        summary=dict(
            programs=len(rows),
            sources=len(sources),
            disciplines=dict(sorted(Counter(r["discipline"] for r in rows).items())),
            computable_verified_tuition=sum(
                r["tuition"]["upper_usd"] is not None for r in rows
            ),
            minimum_only_tuition=sum(r['tuition']['lower_usd'] is not None and r['tuition']['upper_usd'] is None for r in rows),
            maximum_only_tuition=sum(r['tuition']['lower_usd'] is None and r['tuition']['upper_usd'] is not None for r in rows),
            two_sided_tuition_estimates=sum(r['tuition']['lower_usd'] is not None and r['tuition']['upper_usd'] is not None for r in rows),
            full_eligibility_reviews=sum(
                r["field_coverage"]["remaining_eligibility"]["rule_usable"]
                for r in rows
            ),
            reference_hard_checks_ready=sum(
                r["reference_hard_checks_ready"] for r in rows
            ),
            reference_formal_evidence_ready=sum(
                r["reference_formal_evidence_ready"] for r in rows
            ),
            reviewed_recent_cohorts=sum(r["reviewed_recent_cohorts"] for r in rows),
            reviewed_recent_admitted_cases=sum(
                r["reviewed_recent_admitted_cases"] for r in rows
            ),
            reference_tier_evidence_support={
                t: sum(t in r["reference_supported_tiers"] for r in rows) for t in TIERS
            },
            fields={
                g: dict(
                    bound=sum(r["field_coverage"][g]["evidence_bound"] for r in rows),
                    usable=sum(r["field_coverage"][g]["rule_usable"] for r in rows),
                )
                for g in GROUPS
            },
        ),
        programs=rows,
        repair_queue=[
            dict(
                program_id=r["program_id"],
                priority=r["repair_priority"],
                fields=r["next_required_reviews"],
            )
            for r in sorted(
                rows, key=lambda r: (r["repair_priority"] or 99, r["program_id"])
            )
            if r["repair_priority"]
        ],
        notice="Only existing reviewed snapshots are audited. Candidate source tiers do not authorize personalized tiers. Missing credits for term-priced degrees are recorded without treating them as per-credit pricing inputs.",
    )


def screen_candidates(index, review, programs):
    term, year = index["intake"].lower().split()
    if f"{year}-{term}" != review["target_intake"]:
        raise ValueError("CANDIDATE_INTAKE_MISMATCH")
    rows = index["rows"]
    ids = [r["source_id"] for r in rows]
    if len(ids) != index["expected_rows"] or len(ids) != len(set(ids)):
        raise ValueError("CANDIDATE_COUNT_OR_UNIQUENESS")
    if any(
        r["verification_status"] != "community_unverified"
        or r["recommendation_eligible"] != 0
        for r in rows
    ):
        raise ValueError("CANDIDATE_PROMOTION_FORBIDDEN")
    by_id = {r["source_id"]: r for r in rows}
    catalog_ids = {p.program_id for p in programs}
    linked = {}
    for link in review["catalog_links"]:
        sid, pid = link["candidate_source_id"], link["program_id"]
        if sid not in by_id or pid not in catalog_ids or sid in linked:
            raise ValueError("INVALID_CATALOG_LINK")
        linked[sid] = pid
    if len(set(linked.values())) != len(linked) or set(linked.values()) != catalog_ids:
        raise ValueError("CATALOG_LINKS_MUST_COVER_EACH_PROGRAM_ONCE")
    queued = {}
    proposed = set()
    for item in review["first_expansion_batch"]:
        sid, pid = item["candidate_source_id"], item["proposed_program_id"]
        if (
            sid not in by_id
            or sid in linked
            or sid in queued
            or pid in proposed
            or pid in catalog_ids
        ):
            raise ValueError("DUPLICATE_OR_UNKNOWN_EXPANSION_ID")
        if (
            item["promotion_status"] != "not_imported"
            or by_id[sid]["source_reports_halted"]
        ):
            raise ValueError("EXPANSION_CANNOT_PROMOTE_OR_IGNORE_HALTED_LEAD")
        url = urlsplit(item["official_url"])
        if (
            url.scheme != "https"
            or url.username
            or url.password
            or url.port not in {None, 443}
            or item["official_url"] != by_id[sid]["program_url"]
        ):
            raise ValueError("REVIEW_SOURCE_URL_MISMATCH")
        queued[sid] = item
        proposed.add(pid)
    inventory = []
    for row in sorted(rows, key=lambda r: r["source_id"]):
        sid = row["source_id"]
        status = (
            "already_linked_identity"
            if sid in linked
            else "first_batch_review"
            if sid in queued
            else "halt_report_needs_official_check"
            if row["source_reports_halted"]
            else "not_selected"
        )
        inventory.append(
            dict(
                source_id=sid,
                screening_status=status,
                catalog_program_id=linked.get(sid),
                candidate_verification_status="community_unverified",
                recommendation_eligible=False,
                review_flags=row["review_flags"],
            )
        )
    return dict(
        source_commit=index["source_commit"],
        source_sha256=index["source_sha256"],
        source_url=index["source_url"],
        upstream_generated=index["upstream_generated"],
        intake=index["intake"],
        attribution=index["attribution"],
        summary=dict(
            total=len(rows),
            screening_counts=dict(
                sorted(Counter(r["screening_status"] for r in inventory).items())
            ),
            doctoral_scope_review=sum(
                "source_mentions_doctoral_admission" in r["review_flags"] for r in rows
            ),
            source_reports_halted=sum(bool(r["source_reports_halted"]) for r in rows),
            candidate_recommendation_eligible=0,
        ),
        inventory=inventory,
        first_expansion_batch=list(queued.values()),
        notice="Preliminary official-page review does not import an identity or verify numerical admissions/tuition facts. No DP data is used; tracker metadata remains unverified.",
    )


def markdown_report(report):
    audit = report["catalog"]
    summary = audit["summary"]
    pool = report["candidates"]
    lines = [
        "# M6.1 catalog coverage audit",
        "",
        f"Audit date: {audit['as_of_date']} · Target intake: {audit['target_intake']} · Snapshot mode · Model/network requests: 0/0",
        "",
        f"Reviewed catalog: **{summary['programs']} programs / {summary['sources']} sources**. Verified computable tuition: **{summary['computable_verified_tuition']}**. Complete reviewed eligibility: **{summary['full_eligibility_reviews']}**.",
        f"Of these tuition upper bounds, **{summary.get('two_sided_tuition_estimates', summary['computable_verified_tuition'])}** have two-sided estimates and **{summary.get('maximum_only_tuition', 0)}** are conservative ceilings only. A ceiling is not a quoted bill; a budget below it remains unknown rather than automatically failing.",
        f"Verified tuition minimum only: **{summary['minimum_only_tuition']}**. These bounds may exclude insufficient published-rate budgets but never establish affordability.",
        "An `english_minimum` rule supports score-floor screening only. Meeting that floor leaves English eligibility unknown until the complete applicable policy is verified.",
        f"For the fixed fictional profile, **{summary['reference_formal_evidence_ready']}** program has eligibility, goal and tier evidence for formal output. This is a test scenario, not a quality score.",
        "",
        "## Existing programs",
        "",
        "| Program / campus | Verified tuition upper USD | Reference hard checks | Tier evidence for reference profile | Catalog reviews still needed |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for r in audit["programs"]:
        lines.append(
            f"| {r['university']} — {r['degree']}, {r['campus']} | {r['tuition']['upper_usd'] or 'Unknown'} | {r['reference_hard_status']} | {', '.join(r['reference_supported_tiers']) or 'None'} | {', '.join(r['next_required_reviews']) or 'No required gap for this profile'} |"
        )
    lines += [
        "",
        "## Bound evidence versus usable rules",
        "",
        "| Field group | Bound evidence / programs | Usable rule / programs |",
        "| --- | ---: | ---: |",
    ]
    lines += [
        f"| {g} | {v['bound']} | {v['usable']} |" for g, v in summary["fields"].items()
    ]
    lines += [
        "",
        "A bound tuition page with no rate is not computable tuition. A recommended GPA is not a hard minimum. Applicant GPA scope/scale issues are listed separately from catalog gaps. Future published rates are estimates, with living expenses excluded.",
        "",
        "## Repair existing records first",
        "",
    ]
    for row in audit["repair_queue"]:
        lines.append(
            f"- Priority {row['priority']}: `{row['program_id']}` — {', '.join(row['fields'])}."
        )
    lines += ["", "## Applicant comparison issues", ""]
    for r in audit["programs"]:
        for issue in r["reference_profile_comparison_issues"]:
            lines.append(
                f"- `{r['program_id']}`: `{issue['reason_code']}` — {issue['explanation']}"
            )
    lines += [
        "",
        "## Candidate screening",
        "",
        f"Pinned upstream: `{pool['source_commit']}`. {pool['summary']['total']} candidate leads; {pool['summary']['source_reports_halted']} source-reported halt flags. These flags require official review.",
        f"Screening counts: `{pool['summary']['screening_counts']}`. Candidate recommendation eligibility remains **0**.",
        "",
        "## First expansion batch: research queue only",
        "",
        "| Order | Proposed degree / campus | Discipline | Official source | Scope still to resolve |",
        "| ---: | --- | --- | --- | --- |",
    ]
    for row in pool["first_expansion_batch"]:
        lines.append(
            f"| {row['priority']} | {row['university']} — {row['proposed_degree_track']}, {row['proposed_campus']} | {row['discipline']} | [Program page]({row['official_url']}) | {row['scope_notes']} |"
        )
    lines += [
        "",
        "Research-queue entries do not establish numerical requirements. Imported facts are restricted to the separately captured, hashed and field-bound official evidence in the selected seed. Missing eligibility and admission-tier evidence remains open.",
        "",
        f"Target expanded catalog: {report['target_catalog_min']}–{report['target_catalog_max']} programs. Current audited count remains {summary['programs']}; the full M6 data gate is **not met**.",
        "",
        "## Provenance and reproducibility",
        "",
        f"Catalog semantic SHA-256: `{audit['data_hash']}`.",
        f"Candidate upstream SHA-256: `{pool['source_sha256']}`.",
        f"Candidate index attribution: [{pool['attribution']['creator']}]({pool['attribution']['project_url']}), [{pool['attribution']['license']}]({pool['attribution']['license_url']}). See `data/review/README.md` for scope and changes.",
        "",
        "This report uses no LLM and no web connection. The manual research notes are separate inputs. It does not modify either SQLite database or the reviewed catalog. Formal benchmark tasks and scores have not been created by this audit.",
        "",
    ]
    return "\n".join(lines)
