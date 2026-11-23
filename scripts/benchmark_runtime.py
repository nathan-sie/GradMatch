"""Execute scripted applicant turns, then grade the resulting records."""

from collections import Counter
from copy import deepcopy
from decimal import Decimal
import gzip
import json
from traceback import extract_tb
from uuid import uuid4

from gradmatch.config import ModelSettings
from gradmatch.schemas import ApplicantProfile
from gradmatch.service import start_task
from gradmatch.session import Session
from gradmatch.storage import PROJECT_ROOT
from gradmatch.validation import blocking_validation_errors
from scripts.benchmark_suite import json_file, scenario_catalog
from scripts.verify_broad_recommendations import BroadFixture


STRATEGIES = {'fixed': 'fixed', 'react': 'react', 'plan_replan': 'plan'}
FINAL_ASSESSMENTS = {'completed', 'insufficient_evidence', 'infeasible'}


def write_json(path, record, *, compress=False):
    temporary = path.with_name(path.name + '.tmp')
    opener = gzip.open if compress else open
    with opener(temporary, 'wt', encoding='utf-8', newline='\n') as file:
        json.dump(record, file, ensure_ascii=False)
        file.write('\n')
    temporary.replace(path)


def requested_fields(result):
    return {field for question in result.get('pending_questions', []) for field in question['requested_fields']}


def clarification(profile, questions, answers, answered, unknown_fields):
    """Respond to requested fields using only scripted applicant facts."""
    available = sorted((questions & answers.keys()) - answered)
    values = profile.model_dump(mode='json')
    changes = {}
    unknown = set(unknown_fields)
    for field in available:
        value = deepcopy(answers[field])
        if value is None:
            unknown.add(field)
            continue
        root, *keys = field.split('.')
        if keys:
            updated = changes.get(root, values[root]) or {}
            current = updated
            for key in keys[:-1]:
                current = current.setdefault(key, {})
            current[keys[-1]] = value
            changes[root] = updated
        else:
            changes[root] = value
        if root == 'english':
            changes['english_status'] = 'known'
        unknown.discard(field)
    return available, changes, unknown


def no_page_fetch(*args, **kwargs):
    raise AssertionError('A snapshot evaluation attempted to fetch an external page.')


def execute_task(case, strategy, config, dataset, attempt, *, model_settings=None):
    """Run the public service on applicant inputs. This function does not receive an oracle."""
    source_programs, sources = scenario_catalog(
        dataset, withhold_tuition_for=case.withhold_tuition_for, evidence_overlay=case.evidence_overlay,
    )
    session = Session(profile=case.profile())
    provider = None if model_settings is not None else BroadFixture()
    settings = model_settings or ModelSettings('fixture', 'offline-fixture', False, '', json_file(PROJECT_ROOT / 'config/app.json'))
    turns = []
    answered = set()
    remaining_followups = iter(case.followups)
    submission = {'message': case.initial_message}
    for index in range(1, case.max_user_turns + 1):
        event_start = len(session.events)
        result = start_task(
            session, request_id=str(uuid4()), programs=source_programs, sources=sources,
            settings=settings, as_of=case.assessment_date or config.evaluation_date, strategy=STRATEGIES[strategy],
            data_mode='snapshot', recommendation_scope='broad', provider=provider,
            fetcher=no_page_fetch, **submission,
        )
        turns.append(result)
        write_json(attempt / f'turn-{index:02}.json.gz', {
            'submission': submission, 'profile': session.profile.model_dump(mode='json'),
            'result': result, 'events': session.events[event_start:],
        }, compress=True)
        if result['status'] == 'needs_input':
            fields, changes, unknown = clarification(session.profile, requested_fields(result),
                case.clarification_answers, answered, session.unknown_fields)
            if not fields:
                break
            answered.update(fields)
            submission = {'changes': changes, 'unknown_fields': sorted(unknown)}
        elif result['status'] in FINAL_ASSESSMENTS:
            followup = next(remaining_followups, None)
            if followup is None:
                break
            submission = followup.model_dump(exclude_defaults=True)
        else:
            break
    return turns, session.profile, sources


def grade_assessment(oracle, final, initial, profile, sources):
    formal = {item['program_id']: item for item in final.get('recommendations', [])}
    preliminary = {item['program_id']: item for item in final.get('preliminary_recommendations', [])}
    pending = {item['program_id']: item for item in final.get('pending_verification', [])}
    excluded = {item['program_id']: item for item in final.get('excluded', [])}
    reports = {pid: row['report'] for pid, row in pending.items()}
    reports.update({pid: row['checks'] for pid, row in formal.items()})
    expected = ApplicantProfile.model_validate({**initial, **oracle.expected_profile_changes}).model_dump(exclude={'profile_version'})
    values = profile.model_dump(exclude={'profile_version'}) if profile else {}
    profile_ok = profile is not None and (values == expected if oracle.preserve_other_profile_fields else all(
        values[key] == expected[key] for key in oracle.expected_profile_changes))
    checks = {
        'profile': profile_ok,
        'final_profile_version': profile is not None and final['profile_version'] == profile.profile_version
        and (oracle.expected_profile_version is None or profile.profile_version == oracle.expected_profile_version),
        'preliminary_count': len(preliminary) >= oracle.minimum_preliminary_count,
        'formal_count': oracle.maximum_formal_count is None or len(formal) <= oracle.maximum_formal_count,
        'required_formal': all(expect.program_id in formal and (
            expect.tier is None or formal[expect.program_id]['tier'] == expect.tier) for expect in oracle.formal),
        'required_exclusions': all(expect.program_id in excluded and (
            expect.reason_code is None or expect.reason_code in excluded[expect.program_id]['reason_codes'])
            for expect in oracle.excluded),
        'required_pending': all(expect.program_id in pending and (
            expect.missing_field is None or expect.missing_field in pending[expect.program_id]['missing_fields'])
            and (expect.reason_code is None or any(check['reason_code'] == expect.reason_code
                 for check in pending[expect.program_id]['report']['checks'])) for expect in oracle.pending),
    }
    if oracle.expected_tier_counts:
        actual_counts = Counter(row['tier'] for row in formal.values())
        lines = final.get('tier_shortfalls', [])
        shortfalls = {row['tier']: row for row in lines}
        checks['tier_shortfall_rows_unique'] = len(lines) == len(shortfalls)
        for tier, expected_count in oracle.expected_tier_counts.items():
            checks[f'tier_count:{tier}'] = actual_counts[tier] == expected_count
            row = shortfalls.get(tier)
            checks[f'tier_shortfall:{tier}'] = (
                row is None if expected_count >= 3 else row is not None
                and row.get('count') == expected_count
                and row.get('shortfall_to_three') == 3 - expected_count
                and bool(row.get('reason'))
            )
    delta = final.get('changes_from_previous', {})
    if oracle.added_program_ids:
        checks['candidates_added'] = set(oracle.added_program_ids) <= set(delta.get('added', []))
    if oracle.removed_program_ids:
        checks['candidates_removed'] = set(oracle.removed_program_ids) <= {
            item['program_id'] for item in delta.get('removed', [])
        }
    for item in oracle.required_checks:
        report = reports.get(item.program_id, {})
        check = next((check for check in report.get('checks', []) if check['rule_id'] == item.rule_id), {})
        tuition = report.get('tuition', {})
        bounds_match = all(
            expected is None or (tuition.get(key) is not None and Decimal(tuition[key]) == expected)
            for key, expected in [('lower_usd', item.tuition_lower_usd), ('upper_usd', item.tuition_upper_usd)]
        )
        checks[f'constraint:{item.program_id}:{item.rule_id}'] = (
            check.get('status') == item.status and check.get('reason_code') == item.reason_code
            and bounds_match and bool(check.get('source_ids'))
            and all(sid in sources and sources[sid].program_id == item.program_id for sid in check['source_ids'])
        )
    return checks


def grade_task(case, oracle, turns, final_profile, sources):
    initial = case.profile().model_dump(exclude={'profile_version'})
    questions = set().union(*(requested_fields(turn) for turn in turns))
    checks = {
        'expected_turn_statuses': [turn['status'] for turn in turns] == oracle.statuses,
        'required_clarifications': set(oracle.required_question_fields) <= questions,
        'same_service_task': bool(turns[0].get('task_id')) and all(
            turn.get('task_id') == turns[0]['task_id'] for turn in turns),
        'validated_results': all(turn.get('validation_passed', False) and not blocking_validation_errors(turn)
                                 for turn in turns if turn['status'] in FINAL_ASSESSMENTS),
        'snapshot_only': all(turn.get('task_usage', {}).get('page_requests') == 0
                             and turn.get('task_usage', {}).get('search_queries') == 0 for turn in turns),
        **grade_assessment(oracle, turns[-1], initial, final_profile, sources),
    }
    for number, expected in oracle.question_fields_by_turn.items():
        questions_at_turn = turns[number - 1].get('pending_questions', []) if number <= len(turns) else []
        fields = [field for question in questions_at_turn for field in question['requested_fields']]
        checks[f'turn:{number}:requested_fields'] = sorted(fields) == sorted(expected)
    for number, expected in oracle.earlier_turns.items():
        if number > len(turns):
            checks[f'turn:{number}:recorded'] = False
            continue
        turn = turns[number - 1]
        summary = turn.get('profile_summary')
        profile = ApplicantProfile.model_validate(summary) if summary is not None else None
        earlier = grade_assessment(expected, turn, initial, profile, sources)
        checks.update({f'turn:{number}:{key}': value for key, value in earlier.items()})
    for turn in turns:
        tiered = turn.get('recommendations', [])
        tentative = turn.get('preliminary_recommendations', [])
        selected = [item['program_id'] for item in (*tiered, *tentative)]
        rejected = {item['program_id'] for item in turn.get('excluded', []) + turn.get('preliminary_excluded', [])}
        checks.setdefault('recommendations_consistent', True)
        checks['recommendations_consistent'] &= (
            len(selected) == len(set(selected)) and not set(selected) & rejected
            and all(item['checks']['recommendation_ready'] for item in tiered)
            and all(item.get('personalized_tier') is None for item in tentative)
        )
        checks.setdefault('official_citations_resolve', True)
        checks['official_citations_resolve'] &= all(
            source['source_id'] in sources and str(sources[source['source_id']].url) == source['url']
            for item in tiered + turn.get('observations', []) for source in item['citations']
        )
    return checks


def evaluate_attempt(case, oracle, strategy, config, dataset, attempt, *, model_settings=None):
    step = 'execute'
    try:
        turns, profile, sources = execute_task(case, strategy, config, dataset, attempt, model_settings=model_settings)
        step = 'grade'
        checks = grade_task(case, oracle, turns, profile, sources)
    except Exception as error:
        write_json(attempt / 'error.json', {
            'step': step, 'type': type(error).__name__,
            'frames': [{'file': frame.filename, 'line': frame.lineno, 'function': frame.name}
                       for frame in extract_tb(error.__traceback__)],
        })
        return {'outcome': 'error', 'error_type': type(error).__name__, 'error_step': step}
    status = turns[-1]['status']
    outcome = 'passed' if all(checks.values()) else 'failed'
    stop_reason = turns[-1].get('task_usage', {}).get('stop_reason')
    if stop_reason == 'SERVICE_TIME_LIMIT':
        outcome = 'timed_out'
    elif status in {'error', 'budget_exhausted', 'stopped'}:
        outcome = status
    return {
        'outcome': outcome, 'checks': checks, 'application_status': status,
        'turns': len(turns), 'elapsed_ms': round(sum(turn['service_latency_ms'] for turn in turns), 2),
        'fixture_model_calls': sum(turn['model_calls'] for turn in turns) if model_settings is None else 0,
        'tool_calls': turns[-1]['task_usage']['tool_calls'],
        **({'model_attempted': any(turn.get('usage') for turn in turns)} if model_settings is not None else {}),
    }
