"""An 83-program recommendation pool with explicitly preliminary CS Grad facts."""

from datetime import date
from decimal import Decimal
import hashlib
import json

from gradmatch.admission_history import OPENCS_TIER_FLOORS, PLANNING_TIERS, apply_opencs_grades, planning_tier
from gradmatch.community import application_fee_label
from gradmatch.ranking import retrieve
from gradmatch.schemas import ProgramRecord
from gradmatch.storage import PROJECT_ROOT


RESEARCH_PATHS_FILE = PROJECT_ROOT / "data/review/research_paths.json"
OPENCS_GRADES_FILE = PROJECT_ROOT / "data/review/opencs_program_grades.json"


MODEL_CONTRACTS = {
    'rank': " M6.3 BROAD CONTRACT: When recommendation_scope=broad, the same ranking call must also select up to eight useful preliminary program recommendations in suggestions. Each program belongs in only one of recommendations or suggestions. Choose suggestion program_id only from allowed_preliminary_program_ids, with reason_check_ids naming existing non-failing checks in preliminary_reports: english, deadline, gre, tuition, reviewed_eligibility or application_info. Community-backed or incomplete candidates are allowed in suggestions even when recommendation_ready=false; do not assign them a tier, probability, verified eligibility or budget pass. Their explanations and source dates are rendered by code from the selected check IDs. Use the full supplied pool, not only the officially reviewed programs. Only source IDs in the corresponding official report check can support an official observation. Keep suggestions=[] for reviewed-only scope. All existing formal tier rules remain in force.",
    'act': " M6.3 BROAD CONTRACT: In broad scope catalog_index contains all 83 program identities. The ranking step receives the community language, GRE and deadline facts. An initial unfiltered search may use limit=83; check and rank the retrieved pool, including unreviewed programs. An exact requested program ID can be searched anywhere in this index. Missing official GPA/tuition does not prevent preliminary suggestions from labelled community facts. Do not spend the task trying to officially verify all 83 records. Use the same shared rank_programs and validate_shortlist tools.",
    'plan': " M6.3 BROAD CONTRACT: In broad scope, an initial empty-scope search covers all 83 maintained programs. Use empty program_ids for following checks/ranking to refer to the retrieved pool. The ranking tool can propose preliminary suggestions from community facts; missing official GPA/tuition does not require fetching every program before ranking. Formal personal tiers still need their original evidence."
}
MODEL_CONTRACTS["rank"] += (
    " Treat allowed_recommendation_program_ids as the allowlist for formal recommendations."
    " Select a tier only when its matching ready_recommendation_options contains supporting"
    " tier_evidence_options. If tier evidence is missing, leave the program pending or choose an"
    " eligible preliminary suggestion."
    " Optional admission_history_options contains program-specific, self-reported decision counts for the"
    " applicant's GPA band, scale, and intake basis. Use eligibility screening and academic or goal fit first."
    " Use this history only as secondary context when choosing, ordering, or explaining preliminary suggestions."
    " Consider both reported admits and rejects and the sample size; a large sample or many admits alone does"
    " not make a program more suitable. These reports establish neither odds nor an official eligibility or tier result."
    " If history informed a suggestion, set its history_evidence_id to the supplied ID for that exact program."
    " Otherwise set history_evidence_id to null. Never use these IDs as formal tier evidence or as an official citation."
    " The application assigns preliminary planning labels separately using the available historical reports."
    " For a research goal, prioritize eligible programs in research_path_options. Use the documented route"
    " and the applicant's academic background to compare options. A departmental lab or faculty listing"
    " supports exploring a topic; access to an advisor, lab, funding or a thesis place is unconfirmed."
)
MODEL_CONTRACTS["act"] += (
    " When full_pool_required is true, search the full catalog without a discipline filter. Use"
    " program_ids=[] for checks and ranking. Code enforces full-pool screening on these runs."
    " Use explicit IDs for a focused informational request. catalog_index names programs;"
    " only live-mode rows with registered sources include source IDs."
)
MODEL_CONTRACTS["plan"] += (
    " When full_pool_required is true, use empty program_ids for search, checks and ranking."
    " The execution tools screen the full catalog in this mode."
)


def install_provider_instructions(instructions):
    """Update the existing instruction dictionary without recreating provider classes."""
    for purpose, text in MODEL_CONTRACTS.items():
        instructions[purpose] = instructions[purpose].split(' M6.3 BROAD CONTRACT:', 1)[0] + text


def build_broad_catalog(programs, sources):
    from gradmatch.directory import build_directory

    directory = build_directory(programs, sources)
    by_id = {p.program_id: p for p in programs}
    result, entries = [], {}
    for row in directory['records']:
        pid = row['linked_program_id'] or 'community-' + row['source_id']
        program = by_id.get(pid)
        if program is None:
            title = row['program_name']
            # This classification is a retrieval hint, not a university policy.
            discipline = 'ECE' if any(x in title.lower() for x in ['electrical', 'computer engineering']) else 'CS'
            program = ProgramRecord(program_id=pid, university=row['university'], school='Not independently reviewed',
                program_name=title, degree=title, campus='Needs verification', track='Community-reported program; exact scope needs review',
                discipline=discipline, official_url=row['program_url'], allowed_official_hosts=[],
                candidate_source_id=row['source_id'], catalog_version='m63-community-overlay',
                notes=['Preliminary CS Grad identity. Discipline is a title-based retrieval hint. No official policy or admission tier is established.'])
        result.append(program)
        entries[pid] = dict(facts=row['community_facts'], source_id=row['source_id'],
            source_reports_halted=row['source_reports_halted'], review_flags=row['review_flags'],
            officially_linked=bool(row['linked_program_id']))
    context = dict(entries=entries, source_url=directory['source_url'], source_sha256=directory['source_sha256'],
        snapshot_date=directory['upstream_generated'], intake=directory['source_intake'],
        official_program_count=len(programs), official_source_count=len(sources))
    context['data_hash']=hashlib.sha256(json.dumps(context,sort_keys=True).encode()).hexdigest()
    research_snapshot = RESEARCH_PATHS_FILE.read_bytes()
    context["research_paths"] = json.loads(research_snapshot)
    context["research_paths_hash"] = hashlib.sha256(research_snapshot).hexdigest()
    grade_snapshot = OPENCS_GRADES_FILE.read_bytes()
    context["opencs_grades"] = {
        pid: grade for pid, grade in json.loads(grade_snapshot)["programs"].items()
        if grade in OPENCS_TIER_FLOORS
    }
    context["opencs_grades_hash"] = hashlib.sha256(grade_snapshot).hexdigest()
    return result, context


def research_path_options(profile, selected, context, reports, as_of):
    snapshot = context.get("research_paths")
    if not snapshot or profile.goal != "research" or as_of < date.fromisoformat(snapshot["reviewed_on"]):
        return {}
    paths = snapshot["programs"]
    return {
        program.program_id: {**paths[program.program_id], "reviewed_on": snapshot["reviewed_on"]}
        for program in retrieve(profile, selected, len(selected))
        if program.program_id in paths and reports[program.program_id]["eligible_for_preliminary"]
    }


def _rounds(facts, profile):
    result = []
    for row in facts['rounds']:
        label = row['label'].lower()
        if any(word in label for word in ['scholarship', 'fellowship', 'reduced app fee', 'app fee discount']):
            continue
        if profile.applicant_category == 'domestic' and 'international' in label:
            continue
        if profile.study_mode == 'part_time' and ('full-time only' in label or 'full time only' in label):
            continue
        result.append(row)
    return result


def screen_program(profile, program, report, context, *, as_of):
    """Code-owned preliminary checks; no unofficial value establishes a verified pass."""
    entry = context['entries'][program.program_id]
    facts = entry['facts']
    official = {c.rule_id: c for c in report.checks}
    same_cycle = bool(profile.intake and f'{profile.intake.term.title()} {profile.intake.year}' == context['intake'])
    checks = []

    def add(rule, status, explanation, basis='community_reported'):
        checks.append(dict(rule_id=rule, status=status, explanation=explanation, basis=basis))

    failed_official = [c for c in report.checks if c.status == 'fail']
    if failed_official:
        add('reviewed_eligibility', 'fail', '; '.join(c.explanation for c in failed_official), 'reviewed_official')
    else:
        add('reviewed_eligibility', 'unknown', 'Official eligibility is incomplete; missing facts do not establish a pass.', 'reviewed_official')
    if same_cycle and entry['source_reports_halted']:
        add('availability', 'fail', 'CS Grad reports a halt for this intake; confirm current availability.')
    elif 'source_mentions_doctoral_admission' in entry['review_flags']:
        add('availability', 'fail', 'The reported entry describes a doctoral admission route, rather than an independently reviewed terminal master route.')
    else:
        add('availability', 'unknown', 'Current admission availability and exact program scope still need confirmation.')

    english = official.get('english')
    if english and english.status in {'pass', 'fail', 'not_applicable'}:
        add('english', english.status.value, english.explanation, 'reviewed_official')
    elif not same_cycle:
        add('english', 'unknown', 'The tracker score policies apply only to ' + context['intake'] + '; the selected intake needs review.')
    elif profile.english is None:
        add('english', 'unknown', 'Provide the selected English test and original score to compare the reported policy.')
    else:
        score = profile.english
        rule = next(r for r in facts['language'] if r['test'] == score.version)
        mismatch = score.test_date and ((score.version == 'toefl_120' and score.test_date >= date(2026, 1, 21))
            or (score.version == 'toefl_6' and score.test_date < date(2026, 1, 21)))
        if mismatch:
            add('english', 'unknown', 'The test version/date need correction; no score conversion is performed.')
        elif rule['kind'] == 'not_accepted':
            add('english', 'fail', 'CS Grad reports the selected test is not accepted; confirm alternatives.')
        elif rule['reported_total'] is not None:
            below = score.total < Decimal(rule['reported_total'])
            add('english', 'fail' if below else 'reported_floor_met',
                f"{rule['test_label']} {score.total}: " + ('below' if below else 'at/above')
                + f" the reported overall minimum {rule['reported_total']}. Subscores, test age, waivers and other conditions remain unverified.")
        else:
            add('english', 'unknown', rule['test_label'] + ': ' + rule['summary'] + '; this is not a verified overall-minimum pass.')

    deadline = official.get('deadline')
    next_round = None
    if deadline and deadline.status in {'pass', 'fail'}:
        add('deadline', deadline.status.value, deadline.explanation, 'reviewed_official')
    elif not same_cycle:
        add('deadline', 'unknown', 'No tracker deadline is carried over to another intake.')
    else:
        rounds = _rounds(facts, profile)
        upcoming = sorted((r for r in rounds if date.fromisoformat(r['date']) >= as_of), key=lambda r: r['date'])
        conflict = any('conflict' in r['label'].lower() for r in rounds)
        if upcoming:
            next_round = upcoming[0]
            today = date.fromisoformat(next_round['date']) == as_of
            add('deadline', 'unknown' if today or conflict else 'reported_date_available',
                f"Listed round: {next_round['date']} — {next_round['label']}. "
                + ('The cutoff time/time zone or conflicting schedule needs confirmation.' if today or conflict
                   else 'Verify audience, cutoff time and current availability before applying.'))
        elif rounds and not conflict and any('only deadline' in r['label'].lower() or 'only round' in r['label'].lower() or 'final' in r['label'].lower() for r in rounds):
            add('deadline', 'fail', 'All applicable listed rounds have passed, including an explicitly labelled final/only round. Verify whether the program has published an update.')
        else:
            add('deadline', 'unknown', 'No future applicable round is established; a past priority/scholarship date alone does not close admission.')

    gre = official.get('gre')
    if gre and gre.status in {'pass', 'fail', 'not_applicable'}:
        add('gre', gre.status.value, gre.explanation, 'reviewed_official')
    elif same_cycle:
        marker = facts['reported_gre']
        add('gre', 'reported_optional' if marker in {'optional', 'not_required', 'not_accepted'} else 'unknown',
            'Reported GRE policy: ' + marker.replace('_', ' ') + '. ' + ('A GRE result has not been provided; confirm the requirement.' if marker == 'required' and profile.gre is None else 'Check accepted format, validity and any exceptions.'))
    else:
        add('gre', 'unknown', 'The selected intake has no applicable tracker GRE review.')
    tuition = official.get('tuition')
    add('tuition', tuition.status.value, tuition.explanation, 'reviewed_official')
    add('application_info', 'reported_information', 'A reported application portal and dated community policy snapshot are available.')
    return dict(program_id=program.program_id, profile_version=profile.profile_version, as_of_date=str(as_of),
        official_hard_checks_passed=report.hard_checks_status == "pass",
        eligible_for_preliminary=not any(c['status'] == 'fail' for c in checks), checks=checks,
        next_listed_round=next_round, listed_rounds=facts['rounds'], application_url=facts['application_url'],
        application_fee=application_fee_label(facts), reported_gre=facts['reported_gre'],
        reported_language=[{k:v for k,v in r.items() if k != 'original_value'} for r in facts['language']],
        source_url=context['source_url'], source_date=context['snapshot_date'], source_intake=context['intake'],
        source_status='community_unverified')


def compact_program(program, formal_ids):
    fields = {"program_id", "university", "program_name", "discipline"}
    if program.allowed_official_hosts:
        fields.update({"campus", "track"})
    if program.program_id in formal_ids:
        fields.update({"goal_features", "admission_evidence"})
    return program.model_dump(mode="json", include=fields)


def compact_report(report):
    return dict(program_id=report.program_id, profile_version=report.profile_version,
        hard_checks_status=report.hard_checks_status.value, recommendation_ready=report.recommendation_ready,
        unknown_checks=[c.rule_id for c in report.checks if c.status=='unknown'],
        checks=[dict(rule_id=c.rule_id,status=c.status.value,reason_code=c.reason_code,source_ids=c.source_ids) for c in report.checks if c.status!='unknown'])


def ranking_report(report):
    """Keep cited checks for follow-up answers and computed values for ranking."""
    return {
        'program_id': report.program_id,
        'recommendation_ready': report.recommendation_ready,
        'checks': {check.rule_id: [check.status.value, check.reason_code, *check.source_ids]
                   for check in report.checks if check.source_ids},
        'tuition_usd': report.tuition.model_dump(mode='json', include={'lower_usd', 'upper_usd', 'rate_year'}),
    }


def compact_screen(screen, profile):
    return dict(program_id=screen['program_id'],
        checks={check['rule_id']: check['status'] for check in screen['checks']},
        next_listed_round=screen['next_listed_round'], reported_gre=screen['reported_gre'],
        reported_language=[{k:v for k,v in rule.items() if k in {'test','kind','summary'}}
            for rule in screen['reported_language'] if not profile.english or rule['test']==profile.english.version])


def summarize_action_observation(observation):
    """Pass recent outcomes to the next decision without duplicating the full audit log."""
    result = observation['result']
    data = result.get('data') or {}
    summary = {}
    match observation['tool']:
        case 'search_programs':
            summary['program_count'] = len(data.get('programs', []))
        case 'check_constraints':
            summary['checked_count'] = len(data.get('reports', []))
        case 'rank_programs':
            summary['draft_status'] = (data.get('draft') or {}).get('status')
        case 'validate_shortlist':
            summary['status'] = data.get('status')
            summary['validation_errors'] = data.get('validation_errors', [])[:8]
        case 'fetch_official_page':
            summary = {k: data[k] for k in ('facts', 'missing_fields', 'effective_groups') if k in data}
    item = {k: observation[k] for k in ('tool', 'profile_version', 'evidence_version')}
    item['result'] = {k: result[k] for k in ('ok', 'error', 'warnings', 'evidence_ids') if k in result}
    item['result']['data'] = summary
    return item


def finish_broad_result(result, draft, profile, programs, retrieved, context, reports, *, deterministic_only=False,
                        history_options=None, history_snapshot_hash=None, planning_history=None, prioritize_research=True):
    """Validate model-selected IDs and attach actual recommendations to the assessment."""
    from gradmatch.validation import identity, blocking_validation_errors

    selected = {p.program_id:p for p in retrieved}
    formal_ids = {r['program_id'] for r in result['recommendations']}
    allowed = {pid for pid in selected if reports[pid]['eligible_for_preliminary']}
    history_options = history_options or {}
    planning_history = planning_history or {}
    planning = {
        pid: planning_tier(planning_history.get(pid), hard_checks_passed=reports[pid]["official_hard_checks_passed"])
        for pid in allowed - formal_ids
    }
    suggestions = list(draft.suggestions) if draft else []
    method = 'model_selected'
    research_options = research_path_options(profile, retrieved, context, reports, date.fromisoformat(result["as_of_date"]))
    if deterministic_only:
        from gradmatch.ranking import PreliminaryRecommendationDraft
        def key(pid):
            checks = reports[pid]['checks']
            positives = sum(c['status'] in {'pass', 'not_applicable', 'reported_floor_met', 'reported_date_available', 'reported_optional'} for c in checks)
            return (-PLANNING_TIERS.index(planning[pid]["label"]), -positives,
                    selected[pid].university.casefold(), selected[pid].program_name.casefold())
        suggestions = [PreliminaryRecommendationDraft(program_id=pid, reason_check_ids=['english', 'deadline', 'gre']) for pid in sorted(allowed - formal_ids,key=key)[:8]]
        method = 'deterministic_screening'
    accepted, seen = [], set()
    for item in suggestions:
        codes = []
        if item.program_id in seen:codes.append('DUPLICATE_PRELIMINARY_PROGRAM')
        seen.add(item.program_id)
        if item.program_id not in allowed:codes.append('PRELIMINARY_PROGRAM_NOT_ELIGIBLE_OR_RETRIEVED')
        screen = reports.get(item.program_id)
        checks = {c['rule_id']:c for c in screen['checks']} if screen else {}
        if not item.reason_check_ids or any(k not in checks or checks[k]['status']=='fail' for k in item.reason_check_ids):
            codes.append('UNSUPPORTED_PRELIMINARY_REASON')
        history_id = getattr(item, "history_evidence_id", None)
        history = history_options.get(item.program_id)
        if history_id is not None and (history is None or history_id != history["evidence_id"]):
            codes.append("UNSUPPORTED_ADMISSION_HISTORY_REFERENCE")
        if codes:
            result['validation_errors'].append(dict(program_id=item.program_id,codes=codes))
            continue
        if item.program_id in formal_ids:
            result['validation_warnings'].append({
                'program_id': item.program_id, 'code': 'PRELIMINARY_DUPLICATE_OF_FORMAL',
            })
            continue
        suggestion = suggestion_record(selected[item.program_id], screen, method,
                                       [checks[k] for k in dict.fromkeys(item.reason_check_ids)])
        if history_id is not None:
            suggestion["admission_history_evidence"] = history
        accepted.append(suggestion)
    for item in accepted:
        if item["program_id"] in research_options:
            item["research_fit"] = research_options[item["program_id"]]
    if (prioritize_research and research_options and len(retrieved) == len(programs)
            and (deterministic_only or (draft and draft.profile_version == profile.profile_version))):
        matching = [item for item in accepted if "research_fit" in item]
        supplemental = [pid for pid in research_options if pid not in formal_ids and pid not in seen]
        for pid in supplemental[:max(0, 5 - len(matching))]:
            screen = reports[pid]
            item = suggestion_record(selected[pid], screen, "research_path_evidence",
                                     [check for check in screen["checks"] if check["rule_id"] in {"english", "deadline", "gre"}])
            item["research_fit"] = research_options[pid]
            matching.append(item)
        accepted = (matching + [item for item in accepted if "research_fit" not in item])[:8]
    grades = context["opencs_grades"]
    for item in accepted + result["recommendations"]:
        if item["program_id"] in grades:
            item["opencs_grade"] = grades[item["program_id"]]
    for item in accepted:
        item["planning_tier"] = planning[item["program_id"]]
    apply_opencs_grades(accepted)
    blocked = [dict(program_id=pid,identity=identity(p),reasons=[c for c in reports[pid]['checks'] if c['status']=='fail'])
        for pid,p in selected.items() if not reports[pid]['eligible_for_preliminary']]
    blocked_ids = {r['program_id'] for r in blocked}
    result['pending_verification'] = [r for r in result['pending_verification'] if r['program_id'] not in blocked_ids]
    result.update(recommendation_scope='broad', preliminary_recommendations=accepted, preliminary_excluded=blocked,
        preliminary_selection_method=method, recommendation_catalog_count=len(programs),
        community_snapshot=dict(source_url=context['source_url'],source_date=context['snapshot_date'],intake=context['intake'],source_sha256=context['source_sha256']),
        community_data_hash=context['data_hash'],
        recommendation_data_hash=hashlib.sha256(json.dumps({
            "programs": result["data_hash"], "community": context["data_hash"],
            "research_paths": context.get("research_paths_hash"),
            "opencs_grades": context["opencs_grades_hash"],
        }, sort_keys=True).encode()).hexdigest(),
        reviewed_program_count=context['official_program_count'], validation_passed=not blocking_validation_errors(result),
        admission_history_ranking={
            "enabled": history_snapshot_hash is not None,
            "snapshot_hash": history_snapshot_hash,
            "offered_options": len(history_options),
            "referenced_suggestions": sum("admission_history_evidence" in item for item in accepted),
            "matched_planning_options": sum(pid in planning_history for pid in planning),
            "suggestions_with_planning_evidence": sum(item["planning_tier"]["history"] is not None for item in accepted),
        })
    return result


def suggestion_record(program, screen, method, reasons):
    from gradmatch.validation import identity

    return dict(program_id=program.program_id, identity=identity(program), recommendation_basis="preliminary_community",
                selection_method=method, personalized_tier=None, reasons=reasons, checks=screen,
                limitations=["This recommendation uses preliminary information and is not a verified eligibility pass.",
                             "Missing GPA, tuition, preparation or admission-case evidence remains unresolved. No personal admission tier is assigned."])
