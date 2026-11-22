"""Exercise the offline evaluator's data boundary and resume semantics."""

from collections import Counter
import gzip
import json
from types import SimpleNamespace

import pytest

from gradmatch.broad_catalog import build_broad_catalog
from gradmatch.storage import PROJECT_ROOT
from scripts import run_benchmark
from scripts.benchmark_runtime import evaluate_attempt
from scripts.benchmark_suite import json_file, load_suite, scenario_catalog
from scripts.summarize_results import metrics


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
