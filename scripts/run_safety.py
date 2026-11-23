"""Run the frozen safety corpus against GradMatch's offline boundary fixtures."""

import argparse
from collections import Counter
from contextlib import closing
from pathlib import Path
import socket
import sqlite3
from unittest.mock import patch
from uuid import uuid4

from gradmatch.providers import OpenAIProvider
from gradmatch.storage import PROJECT_ROOT
from scripts.benchmark_runtime import STRATEGIES, write_json
from scripts.benchmark_suite import hash_json, json_file, load_suite, read_jsonl
from scripts.run_benchmark import LOCK_FILES, engine_hash, run_entry
from scripts.safety_runtime import COUNTS, SafetyOracle, SafetyTask, evaluate_safety


def load_safety(tasks_path, oracle_path, config_path):
    formal = PROJECT_ROOT / 'eval/formal'
    config, dataset, hosts, _ = load_suite(formal / 'tasks.jsonl', formal / 'oracles.jsonl', config_path, split='formal')
    tasks = read_jsonl(tasks_path, SafetyTask)
    oracles = read_jsonl(oracle_path, SafetyOracle)
    if tasks.keys() != oracles.keys() or Counter(case.category for case in tasks.values()) != COUNTS:
        raise ValueError('Safety tasks and references must match the 15/10/10/10/5 distribution.')
    if len({case.prompt for case in tasks.values()}) != len(tasks):
        raise ValueError('Each safety case needs distinct prompt text.')
    for case in tasks.values():
        if case.host_task_id not in hosts or (case.entry == 'official_page') != (case.probe == 'document'):
            raise ValueError(f'Invalid host or entry for {case.task_id}.')
    return config, (dataset, hosts), tasks, oracles


def summarize_safety(directory):
    manifest = json_file(directory / 'manifest.json')
    rows = []
    for entry in manifest['entries']:
        record = directory / 'entries' / entry['task_id'] / entry['strategy'] / 'attempt-001/result.json'
        rows.append({**entry, 'outcome': json_file(record)['outcome'] if record.exists() else 'not_run'})
    return {
        'mode': manifest['execution_mode'], 'scheduled': len(rows),
        'recorded': sum(row['outcome'] != 'not_run' for row in rows),
        'outcomes': dict(Counter(row['outcome'] for row in rows)),
        'by_strategy': {
            strategy: dict(Counter(row['outcome'] for row in rows if row['strategy'] == strategy))
            for strategy in dict.fromkeys(row['strategy'] for row in rows)
        },
        'paid_model_requests': 0, 'model_safety_scores': 'not_measured',
    }


def run(args):
    config, context, tasks, oracles = load_safety(args.suite, args.oracle, args.config)
    directory = args.run_dir or PROJECT_ROOT / 'work/safety' / uuid4().hex
    hosts = context[1]
    host_ids = sorted({case.host_task_id for case in tasks.values()})
    manifest = {
        'execution_mode': 'offline_boundary_fixture', 'snapshot': config.model_dump(mode='json'),
        'engine_hash': engine_hash(),
        'harness_hash': hash_json([path.read_text(encoding='utf-8') for path in
                                   (Path(__file__), Path(__file__).with_name('safety_runtime.py'))]),
        'tasks_hash': hash_json([row.model_dump(mode='json') for row in tasks.values()]),
        'oracles_hash': hash_json([row.model_dump(mode='json') for row in oracles.values()]),
        'host_profiles_hash': hash_json({tid: hosts[tid].profile().model_dump(mode='json') for tid in host_ids}),
        'entries': [{'task_id': case.task_id, 'category': case.category, 'strategy': strategy}
                    for case in tasks.values() for strategy in args.strategies],
    }
    directory.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(directory / '.run-lock.sqlite', timeout=0)) as lock:
        lock.execute('BEGIN IMMEDIATE')
        path = directory / 'manifest.json'
        if path.exists():
            if not args.resume or json_file(path) != manifest:
                raise ValueError('Resume requires the saved safety manifest to match exactly.')
        elif any(item.name not in LOCK_FILES for item in directory.iterdir()):
            raise ValueError('A new run directory must be empty.')
        else:
            write_json(path, manifest)
        print(f'{len(manifest["entries"])} offline boundary executions. Run: {directory.resolve()}', flush=True)
        if args.dry_run:
            return 0
        count = 0
        with (patch.object(OpenAIProvider, 'generate', side_effect=AssertionError('Real calls are disabled.')),
              patch.object(socket, 'getaddrinfo', side_effect=AssertionError('DNS is disabled.')),
              patch.object(socket.socket, 'connect', side_effect=AssertionError('Network access is disabled.'))):
            for entry in manifest['entries']:
                tid = entry['task_id']
                if run_entry(directory, entry, tasks[tid], oracles[tid], config, context, evaluator=evaluate_safety):
                    count += 1
                if args.max_new_runs is not None and count >= args.max_new_runs:
                    break
        report = summarize_safety(directory)
        write_json(directory / 'summary.json', report)
        print(f'New executions: {count}. Outcomes: {report["outcomes"]}. Paid requests: 0.')
        return int(report['recorded'] == report['scheduled'] and
                   report['outcomes'].get('boundary_pass', 0) != report['scheduled'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', type=Path, default=PROJECT_ROOT / 'eval/safety/tasks.jsonl')
    parser.add_argument('--oracle', type=Path, default=PROJECT_ROOT / 'eval/safety/oracles.jsonl')
    parser.add_argument('--config', type=Path, default=PROJECT_ROOT / 'config/eval_formal.json')
    parser.add_argument('--strategies', nargs='+', choices=STRATEGIES, default=list(STRATEGIES))
    parser.add_argument('--run-dir', type=Path)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--max-new-runs', type=int)
    args = parser.parse_args()
    if len(args.strategies) != len(set(args.strategies)) or (args.max_new_runs is not None and args.max_new_runs < 1):
        parser.error('Choose distinct strategies and a positive execution limit.')
    try:
        return run(args)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    raise SystemExit(main())
