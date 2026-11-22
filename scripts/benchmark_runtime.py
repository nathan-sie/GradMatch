"""Execute scripted applicant turns, then grade the resulting records."""

from copy import deepcopy
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


def execute_task(case, strategy, config, dataset, attempt):
    """Run the public service on applicant inputs. This function does not receive an oracle."""
    source_programs, sources = scenario_catalog(dataset, withhold_tuition_for=case.withhold_tuition_for)
    session = Session(profile=case.profile())
    provider = BroadFixture()
    settings = ModelSettings('fixture', 'offline-fixture', False, '', json_file(PROJECT_ROOT / 'config/app.json'))
    turns = []
    answered = set()
    remaining_followups = iter(case.followups)
    submission = {'message': case.initial_message}
    for index in range(1, case.max_user_turns + 1):
        event_start = len(session.events)
        result = start_task(
            session, request_id=str(uuid4()), programs=source_programs, sources=sources,
            settings=settings, as_of=config.evaluation_date, strategy=STRATEGIES[strategy],
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


def grade_task(case, oracle, turns, final_profile, sources):
    final = turns[-1]
    formal = {item['program_id']: item for item in final.get('recommendations', [])}
    preliminary = {item['program_id']: item for item in final.get('preliminary_recommendations', [])}
    pending = {item['program_id']: item for item in final.get('pending_verification', [])}
    excluded = {item['program_id']: item for item in final.get('excluded', [])}
    questions = set().union(*(requested_fields(turn) for turn in turns))

    initial = case.profile().model_dump(exclude={'profile_version'})
    expected = ApplicantProfile.model_validate({**initial, **oracle.expected_profile_changes}).model_dump(exclude={'profile_version'})
    final_values = final_profile.model_dump(exclude={'profile_version'})
    profile_ok = final_values == expected if oracle.preserve_other_profile_fields else all(
        final_values[key] == expected[key] for key in oracle.expected_profile_changes)
    checks = {
        'expected_turn_statuses': [turn['status'] for turn in turns] == oracle.statuses,
        'required_clarifications': set(oracle.required_question_fields) <= questions,
        'same_service_task': bool(turns[0].get('task_id')) and all(
            turn.get('task_id') == turns[0]['task_id'] for turn in turns),
        'profile': profile_ok,
        'final_profile_version': final['profile_version'] == final_profile.profile_version,
        'validated_results': all(turn.get('validation_passed', False) and not blocking_validation_errors(turn)
                                 for turn in turns if turn['status'] in FINAL_ASSESSMENTS),
        'snapshot_only': all(turn.get('task_usage', {}).get('page_requests') == 0
                             and turn.get('task_usage', {}).get('search_queries') == 0 for turn in turns),
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


def evaluate_attempt(case, oracle, strategy, config, dataset, attempt):
    step = 'execute'
    try:
        turns, profile, sources = execute_task(case, strategy, config, dataset, attempt)
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
        'fixture_model_calls': sum(turn['model_calls'] for turn in turns),
        'tool_calls': turns[-1]['task_usage']['tool_calls'],
    }
