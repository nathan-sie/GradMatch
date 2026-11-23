"""Exercise the offline evaluator's data boundary and resume semantics."""

from collections import Counter
from contextlib import closing
from copy import deepcopy
from datetime import date
from decimal import Decimal
import gzip
import json
import sqlite3
from types import SimpleNamespace

import pytest

from gradmatch.broad_catalog import build_broad_catalog
from gradmatch.agent import BudgetLimit
from gradmatch.catalog import load_seed
from gradmatch.config import ModelSettings
from gradmatch.constraints import check_constraints
from gradmatch.providers import OpenAIProvider
from gradmatch.session import tiering_profile
from gradmatch.storage import PROJECT_ROOT
from scripts import run_benchmark
from scripts.benchmark_evidence import EvidenceOverlay
from scripts.benchmark_model import LEDGER_FILE, RequestLedger, model_request_rows
from scripts.benchmark_runtime import evaluate_attempt, execute_task, grade_task
from scripts.benchmark_suite import AssessmentExpectation, ConstraintExpectation, json_file, load_suite, scenario_catalog
from scripts.summarize_results import metrics, summarize
from scripts.verify_broad_recommendations import BroadFixture


TASKS = PROJECT_ROOT / 'eval/development/tasks.jsonl'
ORACLES = TASKS.with_name('oracles.jsonl')
CONFIG = PROJECT_ROOT / 'config/eval.json'


@pytest.fixture(scope='module')
def suite():
    return load_suite(TASKS, ORACLES, CONFIG)


def test_development_suite_and_formal_gate(suite):
    config, _, tasks, oracles = suite
    assert Counter(case.category for case in tasks.values()) == {
        'initial': 3, 'followup': 3, 'clarification': 3, 'evidence_gap': 3, 'shortfall': 3,
    }
    manifest = run_benchmark.manifest_for(config, tasks, oracles, ['fixed', 'react', 'plan_replan'], 'development')
    assert len(manifest['entries']) == 45
    assert [entry['strategy'] for entry in manifest['entries'][:3]] == ['fixed', 'react', 'plan_replan']
    with pytest.raises(ValueError, match='formal suite must have'):
        load_suite(TASKS, ORACLES, CONFIG, split='formal')


def test_changed_snapshot_is_rejected(tmp_path):
    config = tmp_path / 'wrong.json'
    config.write_text(json.dumps({**json_file(CONFIG), 'snapshot_hash': '0' * 64}), encoding='utf-8')
    with pytest.raises(ValueError, match='Snapshot changed'):
        load_suite(TASKS, ORACLES, config)


def test_missing_official_tuition_is_hidden_before_building_broad_catalog(suite):
    _, dataset, tasks, _ = suite
    target = tasks['dev10'].withhold_tuition_for
    programs, sources = scenario_catalog(dataset, withhold_tuition_for=target)
    original = next(program for program in dataset[0] if program.program_id == target)
    assert any(source.program_id == target for source in dataset[1].values())
    assert all(source.program_id != target for source in sources.values())
    broad_programs, _ = build_broad_catalog(programs, sources)
    replacement = next(program for program in broad_programs if program.program_id == target)
    assert replacement.tuition != original.tuition
    assert not replacement.field_sources
    assert len(broad_programs) == 83


def test_conflicting_credits_hide_derived_cost_and_retain_unrelated_evidence(suite):
    config, dataset, _, _ = suite
    target = 'uw-ece-msece-pmp-seattle'
    overlay = EvidenceOverlay(
        program_id=target, field_group='credits', mode='conflict', conflicting_values={'required_credits': '47'},
    )
    programs, sources = scenario_catalog(dataset, evidence_overlay=overlay)
    program = next(p for p in programs if p.program_id == target)
    original = next(p for p in dataset[0] if p.program_id == target)
    assert original.required_credits == 45 and program.required_credits is None
    assert program.tuition.basis == 'unknown'
    disagreements = [sources[sid] for sid in program.field_sources['credits']]
    assert len(disagreements) == 2
    assert all(s.verification_status == 'conflict' and not s.source_excerpt for s in disagreements)
    assert {Decimal(s.verified_values['credits']['required_credits']) for s in disagreements} == {45, 47}
    assert all(not s.source_excerpt and 'tuition' not in s.verified_values
               for s in sources.values() if s.program_id == target)
    checks = {c.rule_id: c for c in check_constraints(
        tiering_profile(), program, sources, as_of=config.evaluation_date,
    ).checks}
    assert checks['tuition'].reason_code == 'MISSING_TUITION_EVIDENCE'
    assert checks['english'].status == 'pass'


def test_checklist_overlay_preserves_duplicate_degree_requirement():
    dataset = load_seed(PROJECT_ROOT / 'data/catalog/dp_batch_review_seed.json')
    target = 'ucsd-ms-cs-la-jolla'
    overlay = EvidenceOverlay(program_id=target, field_group='application_materials', mode='missing')
    programs, sources = scenario_catalog(dataset, evidence_overlay=overlay)
    program = next(p for p in programs if p.program_id == target)
    assert not program.application_materials
    assert 'duplicate_advanced_degree' in program.field_sources
    report = check_constraints(tiering_profile(), program, sources, as_of=date(2026, 11, 22))
    coverage = next(c for c in report.checks if c.rule_id == 'remaining_eligibility')
    assert coverage.reason_code == 'ADDITIONAL_ELIGIBILITY_EVIDENCE_INCOMPLETE'


def test_unknown_date_uses_real_clarification_flow_without_leaking_oracle(suite, tmp_path):
    config, dataset, tasks, oracles = suite
    secret = 'Scoring-only reference text for this test.'
    oracle = oracles['dev11'].model_copy(update={'reference_note': secret})
    result = evaluate_attempt(tasks['dev11'], oracle, 'plan_replan', config, dataset, tmp_path)
    assert result['outcome'] == 'passed', result
    assert result['turns'] == 2
    first, second = [json.loads(gzip.decompress(path.read_bytes())) for path in sorted(tmp_path.glob('turn-*.gz'))]
    assert first['result']['status'] == 'needs_input'
    assert first['result']['task_id'] == second['result']['task_id']
    assert second['submission']['unknown_fields'] == ['english.test_date']
    assert second['profile']['english']['test_date'] is None
    assert second['result']['recommendation_catalog_count'] == 83
    assert secret not in json.dumps([first, second])


def test_exact_question_check_rejects_extra_and_duplicate_fields(suite, tmp_path):
    config, dataset, tasks, oracles = suite
    case = tasks['dev11']
    turns, profile, sources = execute_task(case, 'plan_replan', config, dataset, tmp_path)
    oracle = oracles[case.task_id].model_copy(update={'question_fields_by_turn': {1: ['english.test_date']}})
    check = 'turn:1:requested_fields'
    assert grade_task(case, oracle, turns, profile, sources)[check]
    for extra in ('major', 'english.test_date'):
        questions = turns[0]['pending_questions'] + [{'requested_fields': [extra]}]
        altered = [{**turns[0], 'pending_questions': questions}, *turns[1:]]
        assert not grade_task(case, oracle, altered, profile, sources)[check]


def test_constraint_oracle_checks_tuition_value_alongside_status_and_citation(suite, tmp_path):
    config, dataset, tasks, oracles = suite
    case = tasks['dev01']
    turns, profile, sources = execute_task(case, 'fixed', config, dataset, tmp_path)
    estimate = ConstraintExpectation(
        program_id='cmu-msaii-pittsburgh', rule_id='tuition', status='pass',
        reason_code='TUITION_WITHIN_PUBLISHED_RATE_BUDGET', tuition_upper_usd=Decimal('137400'),
    )
    oracle = oracles[case.task_id].model_copy(update={'required_checks': [estimate]})
    check = 'constraint:cmu-msaii-pittsburgh:tuition'
    assert grade_task(case, oracle, turns, profile, sources)[check]
    changed = estimate.model_copy(update={'tuition_upper_usd': Decimal('137399')})
    oracle = oracle.model_copy(update={'required_checks': [changed]})
    assert not grade_task(case, oracle, turns, profile, sources)[check]


def test_tier_shortfall_grade_requires_the_displayed_count_and_reason(suite, tmp_path):
    config, dataset, tasks, oracles = suite
    case = tasks['dev01']
    turns, profile, sources = execute_task(case, 'fixed', config, dataset, tmp_path)
    oracle = oracles[case.task_id].model_copy(update={'expected_tier_counts': {'Lottery': 1, 'Safer': 0}})
    assert all(grade_task(case, oracle, turns, profile, sources).values())
    rows = [{**row, 'reason': ''} if row['tier'] == 'Safer' else row for row in turns[0]['tier_shortfalls']]
    altered = [{**turns[0], 'tier_shortfalls': rows}]
    checks = grade_task(case, oracle, altered, profile, sources)
    assert checks['tier_count:Safer']
    assert not checks['tier_shortfall:Safer']


def test_followup_oracle_grades_the_pre_edit_profile_and_candidate_removal(suite, tmp_path):
    config, dataset, tasks, oracles = suite
    case = tasks['dev04']
    turns, profile, sources = execute_task(case, 'plan_replan', config, dataset, tmp_path)
    original = AssessmentExpectation(expected_profile_version=1)
    oracle = oracles[case.task_id].model_copy(update={
        'earlier_turns': {1: original},
        'expected_profile_version': 2,
        'removed_program_ids': ['cmu-msaii-pittsburgh'],
    })
    assert all(grade_task(case, oracle, turns, profile, sources).values())
    stale = original.model_copy(update={'expected_profile_changes': {'tuition_budget_usd': '50000'}})
    wrong_removal = oracle.model_copy(update={
        'earlier_turns': {1: stale},
        'removed_program_ids': ['rice-mcs-houston'],
    })
    checks = grade_task(case, wrong_removal, turns, profile, sources)
    assert checks['profile']
    assert not checks['turn:1:profile']
    assert not checks['candidates_removed']


def test_grader_requires_actual_full_pool_checks_on_every_assessment(suite, tmp_path):
    config, dataset, tasks, oracles = suite
    case, oracle = tasks['dev04'], oracles['dev04']
    turns, profile, sources = execute_task(case, 'react', config, dataset, tmp_path)
    assert grade_task(case, oracle, turns, profile, sources)['full_pool_screened']

    first = deepcopy(turns[0])
    trace = next(event for event in first['task_usage']['tool_log'] if event['tool'] == 'check_constraints')
    trace['result']['data']['reports'].pop()
    assert not grade_task(case, oracle, [first, turns[1]], profile, sources)['full_pool_screened']


def test_research_oracle_checks_matching_official_evidence_in_first_five(tmp_path):
    root = PROJECT_ROOT / 'eval/formal'
    config, dataset, tasks, oracles = load_suite(
        root / 'tasks.jsonl', root / 'oracles.jsonl', PROJECT_ROOT / 'config/eval_formal.json', split='formal',
    )
    case, oracle = tasks['f-init-050'], oracles['f-init-050']
    turns, profile, sources = execute_task(case, 'react', config, dataset, tmp_path)
    assert oracle.research_evidence_top_k == 5
    assert all(grade_task(case, oracle, turns, profile, sources).values())

    edited = deepcopy(turns)
    edited[0]['preliminary_recommendations'][0]['research_fit'] = edited[0]['preliminary_recommendations'][1]['research_fit']
    assert not grade_task(case, oracle, edited, profile, sources)['top_research_evidence']


def test_summary_counts_missing_and_failed_first_attempts():
    report = metrics([
        {'outcome': 'passed', 'elapsed_ms': 25, 'turns': 2},
        {'outcome': 'failed', 'elapsed_ms': 5, 'turns': 1},
        {'outcome': 'timed_out', 'elapsed_ms': 120, 'turns': 3},
        {'outcome': 'interrupted'}, {'outcome': 'not_run'},
    ])
    assert report['fixture_pass_fraction'] == 1 / 5
    assert report['recorded'] == 4
    assert report['average_latency_ms'] == 50
    assert report['p95_latency_ms'] == 120
    assert report['average_user_turns'] == 2
    assert report['provider_input_tokens'] is None


def test_resume_preserves_interruption_and_does_not_retry_failure(tmp_path, monkeypatch):
    entry = {'task_id': 'dev01', 'category': 'initial', 'strategy': 'fixed', 'repetition': 1}
    parent = tmp_path / 'entries/dev01/fixed'
    first = parent / 'attempt-001'
    first.mkdir(parents=True)
    trace = first / 'turn-01.json.gz'
    trace.write_bytes(b'partial trace')
    monkeypatch.setattr(run_benchmark, 'evaluate_attempt', lambda *_: {'outcome': 'failed'})
    assert run_benchmark.run_entry(tmp_path, entry, None, None, None, None)
    assert json_file(first / 'result.json')['outcome'] == 'interrupted'
    assert trace.read_bytes() == b'partial trace'
    assert json_file(parent / 'attempt-002/result.json')['outcome'] == 'failed'
    assert not run_benchmark.run_entry(tmp_path, entry, None, None, None, None)
    assert not (parent / 'attempt-003').exists()


def test_resume_rejects_different_schedule(tmp_path):
    args = SimpleNamespace(suite=TASKS, oracle=ORACLES, config=CONFIG, split='development',
                           strategies=['fixed'], run_dir=tmp_path, resume=False, dry_run=True)
    assert run_benchmark.run(args) == 0
    args.resume = True
    args.strategies = ['react']
    with pytest.raises(ValueError, match='differs from the saved run'):
        run_benchmark.run(args)


def test_model_runner_meters_first_attempts_and_enforces_cap_across_resume(tmp_path, monkeypatch):
    settings = ModelSettings('openai', 'fixture-model', True, 'fixture-private-key', json_file(PROJECT_ROOT / 'config/app.json'))
    monkeypatch.setattr(run_benchmark, 'load_settings', lambda: settings)
    adapter = BroadFixture()

    def transport(provider, kind, purpose, payload, session):
        draft = adapter.generate(kind, purpose, payload, session)
        session.usage[-1].update(
            model='fixture-model', status='completed', input_tokens=30, output_tokens=10,
            response_id=f'fixture-{len(adapter.calls)}', estimated_cost_usd='0.002',
        )
        return draft

    monkeypatch.setattr(OpenAIProvider, 'generate', transport)
    args = SimpleNamespace(suite=TASKS, oracle=ORACLES, config=CONFIG, split='development',
                           strategies=['fixed'], task_ids=['dev01', 'dev04'], run_dir=tmp_path, resume=False,
                           dry_run=False, live_model=True, max_new_runs=1, max_model_requests=2,
                           max_requests_per_task=4)
    assert run_benchmark.run(args) == 0
    first = summarize(tmp_path)
    assert first['reserved_model_requests_total'] == 1
    assert first['outcomes'] == {'passed': 1, 'not_run': 1}
    assert first['benchmark_scores'] == 'partial'
    assert 'fixture-private-key' not in (tmp_path / 'manifest.json').read_text(encoding='utf-8')
    args.resume = True
    assert run_benchmark.run(args) == 1
    final = summarize(tmp_path)
    assert final['outcomes'] == {'passed': 1, 'budget_exhausted': 1}
    assert final['reserved_model_requests_total'] == len(adapter.calls) == 2
    assert final['average_tokens'] == 40 and final['estimated_model_cost_usd'] == '0.004'
    assert run_benchmark.run(args) == 1
    assert len(adapter.calls) == 2 and summarize(tmp_path) == final


def test_interrupted_call_reservation_survives_reopen(tmp_path, monkeypatch):
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(OpenAIProvider, 'generate', interrupted)
    provider = OpenAIProvider(None)
    session = SimpleNamespace(usage=[])
    with closing(sqlite3.connect(tmp_path / LEDGER_FILE)) as db:
        ledger = RequestLedger(db, 1)
        with ledger.capture('dev01', 'fixed', 1), pytest.raises(KeyboardInterrupt):
            provider.generate(None, 'rank', {}, session)
    assert model_request_rows(tmp_path) == [
        {'task_id': 'dev01', 'strategy': 'fixed', 'attempt': 1, 'usage': None},
    ]
    with closing(sqlite3.connect(tmp_path / LEDGER_FILE)) as db:
        with RequestLedger(db, 1).capture('dev01', 'fixed', 2), pytest.raises(BudgetLimit):
            provider.generate(None, 'rank', {}, session)
