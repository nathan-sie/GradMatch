"""Run reproducible snapshot benchmark fixtures or explicitly capped model evaluations."""

import argparse
from contextlib import ExitStack, closing
from dataclasses import replace
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
from pathlib import Path
import random
import socket
import sqlite3
from unittest.mock import patch
from uuid import uuid4

from gradmatch.broad_catalog import RESEARCH_PATHS_FILE
from gradmatch.config import load_settings
from gradmatch.providers import OpenAIProvider
from gradmatch.storage import PROJECT_ROOT
from scripts.benchmark_runtime import STRATEGIES, evaluate_attempt, write_json
from scripts.benchmark_model import LEDGER_FILE, RequestLedger
from scripts.benchmark_suite import FORMAL_COUNTS, hash_json, json_file, load_suite
from scripts.summarize_results import summarize


LOCK_FILES = {'.run-lock.sqlite', '.run-lock.sqlite-journal'}


def engine_hash():
    paths = [*sorted((PROJECT_ROOT / 'gradmatch').glob('*.py'))]
    paths += [PROJECT_ROOT / 'scripts' / name for name in [
        'benchmark_suite.py', 'benchmark_runtime.py', 'benchmark_evidence.py', 'benchmark_model.py',
        'run_benchmark.py', 'summarize_results.py',
        'verify_broad_recommendations.py', 'm5_fixtures.py',
    ]]
    paths += [PROJECT_ROOT / 'config' / name for name in ['agent.json', 'app.json', 'ranking_rubric.md']]
    paths.append(RESEARCH_PATHS_FILE)
    return hash_json({path.relative_to(PROJECT_ROOT).as_posix():
                      hashlib.sha256(path.read_text(encoding='utf-8').encode()).hexdigest() for path in paths})


def manifest_for(config, tasks, oracles, strategies, split):
    entries = [{'task_id': case.task_id, 'category': case.category, 'strategy': strategy, 'repetition': 1}
               for case in tasks.values() for strategy in strategies]
    manifest = {
        'schema_version': 1, 'split': split, 'execution_mode': 'offline_fixture',
        'config': config.model_dump(mode='json'), 'engine_hash': engine_hash(),
        'suite_hash': hash_json([case.model_dump(mode='json') for case in tasks.values()]),
        'oracle_hash': hash_json([oracle.model_dump(mode='json') for oracle in oracles.values()]),
        'dependencies': {name: version(name) for name in ['langgraph', 'langgraph-checkpoint', 'openai', 'pydantic']},
        'entries': entries,
    }
    if split == 'formal':
        rng = random.Random(20261122)
        manifest['audit_task_ids'] = {
            category: sorted(rng.sample(sorted(case.task_id for case in tasks.values() if case.category == category), 6))
            for category in FORMAL_COUNTS
        }
    return manifest


def run_entry(directory, entry, case, oracle, config, dataset, *, evaluator=None):
    """Return false if this entry already reached a non-interrupted terminal state."""
    parent = directory / 'entries' / entry['task_id'] / entry['strategy']
    number = 1
    while (attempt := parent / f'attempt-{number:03}').exists():
        result_file = attempt / 'result.json'
        if not result_file.exists():
            write_json(result_file, {**entry, 'attempt': number, 'outcome': 'interrupted'})
        elif json_file(result_file)['outcome'] != 'interrupted':
            return False
        number += 1
    attempt.mkdir(parents=True, exist_ok=False)
    metadata = {**entry, 'attempt': number, 'started_at': datetime.now(timezone.utc).isoformat()}
    write_json(attempt / 'started.json', metadata)
    result = (evaluator or evaluate_attempt)(case, oracle, entry['strategy'], config, dataset, attempt)
    write_json(attempt / 'result.json', {**metadata, **result})
    return True


def run(args):
    config, dataset, tasks, oracles = load_suite(args.suite, args.oracle, args.config, split=args.split)
    selected = getattr(args, 'task_ids', None)
    if selected:
        if args.split == 'formal' or len(set(selected)) != len(selected) or not set(selected) <= tasks.keys():
            raise ValueError('Task selection requires distinct development task IDs.')
        tasks = {task_id: tasks[task_id] for task_id in selected}
        oracles = {task_id: oracles[task_id] for task_id in selected}
    directory = args.run_dir or PROJECT_ROOT / 'runs' / f'm64-{uuid4()}'
    manifest = manifest_for(config, tasks, oracles, args.strategies, args.split)
    settings = None
    if getattr(args, 'live_model', False):
        settings = load_settings()
        if not args.dry_run and not settings.ready:
            raise ValueError('An enabled local model configuration is required.')
        session_limit = min(args.max_requests_per_task, settings.limits['max_model_calls_per_session'])
        settings = replace(settings, limits={**settings.limits, 'max_model_calls_per_session': session_limit})
        manifest.update(execution_mode='live_model', model={
            'provider': settings.provider, 'name': settings.model,
            'config_hash': settings.public()['config_hash'], 'max_requests_per_task': session_limit,
            'max_model_requests': args.max_model_requests,
            'pricing_snapshot': settings.limits['pricing'],
        })
    directory.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(directory / '.run-lock.sqlite', timeout=0)) as lock:
        lock.execute('BEGIN IMMEDIATE')
        manifest_path = directory / 'manifest.json'
        if manifest_path.exists():
            if not args.resume:
                raise ValueError('The run directory already has a manifest. Pass --resume to continue it.')
            if json_file(manifest_path) != manifest:
                raise ValueError('The suite, oracle, engine, configuration, or schedule differs from the saved run.')
        elif any(item.name not in LOCK_FILES for item in directory.iterdir()):
            raise ValueError('A new run directory must be empty.')
        else:
            write_json(manifest_path, manifest)
        print(f"Run: {directory.resolve()}\nScheduled executions: {len(manifest['entries'])}"
              f" ({manifest['execution_mode']})", flush=True)
        if settings is not None:
            print(f"Request cap: {args.max_model_requests} total, {session_limit} per task.", flush=True)
        if args.dry_run:
            return 0
        count = 0
        with ExitStack() as stack:
            ledger, evaluator = None, None
            if settings is None:
                stack.enter_context(patch.object(OpenAIProvider, 'generate', side_effect=AssertionError('Fixtures cannot call a real model.')))
                stack.enter_context(patch.object(socket, 'getaddrinfo', side_effect=AssertionError('Fixtures cannot resolve external hosts.')))
                stack.enter_context(patch.object(socket.socket, 'connect', side_effect=AssertionError('Fixtures cannot open network connections.')))
            else:
                path = directory / LEDGER_FILE
                if not path.exists() and any(directory.glob('entries/*/*/attempt-*')):
                    raise ValueError('The model request ledger is missing for an existing run.')
                db = stack.enter_context(closing(sqlite3.connect(path)))
                ledger = RequestLedger(db, args.max_model_requests)

                def evaluator(case, oracle, strategy, config, dataset, attempt):
                    number = int(attempt.name.removeprefix('attempt-'))
                    with ledger.capture(case.task_id, strategy, number):
                        return evaluate_attempt(case, oracle, strategy, config, dataset, attempt, model_settings=settings)

            for entry in manifest['entries']:
                if ledger is not None and ledger.used() >= ledger.maximum:
                    break
                tid = entry['task_id']
                if run_entry(directory, entry, tasks[tid], oracles[tid], config, dataset, evaluator=evaluator):
                    count += 1
                if args.max_new_runs is not None and count >= args.max_new_runs:
                    break
        report = summarize(directory)
        write_json(directory / 'summary.json', report)
        print(f"New executions: {count}. First attempts recorded: {report['recorded']}. "
              f"Model request reservations: {report.get('reserved_model_requests_total', 0)}.")
        return int(report['recorded'] == len(manifest['entries']) and report['passed'] != report['recorded'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, default=PROJECT_ROOT / 'eval/development/tasks.jsonl')
    parser.add_argument('--oracle', type=Path, default=PROJECT_ROOT / 'eval/development/oracles.jsonl')
    parser.add_argument('--config', type=Path, default=PROJECT_ROOT / 'config/eval.json')
    parser.add_argument('--split', choices=['development', 'formal'], default='development')
    parser.add_argument('--mode', choices=['snapshot'], default='snapshot')
    parser.add_argument('--strategies', nargs='+', choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--task-ids', nargs='+', help='Run a selected development pilot.')
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--max-new-runs', type=int)
    parser.add_argument('--live-model', action='store_true', help='Use the configured model in snapshot mode.')
    parser.add_argument('--max-model-requests', type=int, help='Maximum cumulative model requests, including resumes.')
    parser.add_argument('--max-requests-per-task', type=int, default=16, help='Maximum model requests per task session.')
    args = parser.parse_args()
    if len(set(args.strategies)) != len(args.strategies):
        parser.error('Each strategy may appear once.')
    if args.max_new_runs is not None and args.max_new_runs < 1:
        parser.error('--max-new-runs must be positive.')
    if args.live_model and (not args.max_model_requests or args.max_model_requests < 1):
        parser.error('--live-model requires a positive --max-model-requests.')
    task_limit = json_file(PROJECT_ROOT / 'config/agent.json')['max_models']
    if not 1 <= args.max_requests_per_task <= task_limit:
        parser.error(f'--max-requests-per-task must be between 1 and {task_limit}.')
    try:
        return run(args)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
