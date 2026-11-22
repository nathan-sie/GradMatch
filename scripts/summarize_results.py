"""Recompute metrics on the scheduled first attempts for an evaluation run."""

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from statistics import mean, median

from scripts.benchmark_suite import json_file


def metrics(rows):
    counts = Counter(row['outcome'] for row in rows)
    latency = sorted(row['elapsed_ms'] for row in rows if row.get('elapsed_ms') is not None)
    turns = [row['turns'] for row in rows if row.get('turns') is not None]
    return {
        'scheduled': len(rows), 'recorded': len(rows) - counts['not_run'], 'passed': counts['passed'],
        'outcomes': dict(counts), 'fixture_pass_fraction': counts['passed'] / len(rows) if rows else None,
        'latency_samples': len(latency), 'average_latency_ms': mean(latency) if latency else None,
        'median_latency_ms': median(latency) if latency else None,
        'p95_latency_ms': latency[math.ceil(0.95 * len(latency)) - 1] if latency else None,
        'user_turn_samples': len(turns), 'average_user_turns': mean(turns) if turns else None,
        'fixture_model_calls': sum(row.get('fixture_model_calls', 0) for row in rows),
        'paid_model_calls': 0, 'provider_input_tokens': None, 'provider_output_tokens': None,
        'benchmark_scores': 'not_measured',
    }


def summarize(directory):
    manifest = json_file(directory / 'manifest.json')
    if manifest['execution_mode'] != 'offline_fixture':
        raise ValueError('This version summarizes offline fixture runs.')
    rows = []
    for entry in manifest['entries']:
        path = directory / 'entries' / entry['task_id'] / entry['strategy'] / 'attempt-001' / 'result.json'
        outcome = json_file(path) if path.exists() else {'outcome': 'not_run'}
        rows.append({**outcome, **entry})
    by_strategy = {}
    for strategy in dict.fromkeys(row['strategy'] for row in rows):
        group = [row for row in rows if row['strategy'] == strategy]
        by_strategy[strategy] = {
            **metrics(group),
            'by_category': {category: metrics([row for row in group if row['category'] == category])
                            for category in sorted({row['category'] for row in group})},
        }
    return {**metrics(rows), 'execution_mode': manifest['execution_mode'], 'by_strategy': by_strategy}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.runs), indent=2))


if __name__ == '__main__':
    main()
