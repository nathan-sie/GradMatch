"""Recompute metrics on the scheduled first attempts for an evaluation run."""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal
import json
import math
from pathlib import Path
from statistics import mean, median

from scripts.benchmark_model import model_request_rows
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


def live_metrics(rows, usage_by_attempt):
    report = metrics(rows)
    recorded = [row for row in rows if row['outcome'] != 'not_run']
    requests = [usage_by_attempt[(row['task_id'], row['strategy'], 1)] for row in recorded]
    flat = [usage for attempt in requests for usage in attempt]
    costs = [usage['estimated_cost_usd'] for usage in flat if usage and usage.get('estimated_cost_usd') is not None]
    known_cost = sum((Decimal(value) for value in costs), Decimal(0))
    token_rows = [attempt for attempt in requests if all(
        usage and usage.get('input_tokens') is not None and usage.get('output_tokens') is not None for usage in attempt
    )]
    fully_metered = len(token_rows) == len(recorded) and bool(recorded)
    report.pop('fixture_pass_fraction')
    report.pop('fixture_model_calls')
    report.pop('paid_model_calls')
    report.update({
        'task_success_fraction': report['passed'] / report['scheduled'] if rows else None,
        'benchmark_scores': ('measured' if report['recorded'] == report['scheduled'] else
                             'partial' if report['recorded'] else 'not_measured'),
        'reserved_model_requests': len(flat),
        'recorded_provider_requests': sum(usage is not None for usage in flat),
        'provider_response_count': sum(bool(usage and usage.get('response_id')) for usage in flat),
        'provider_models': sorted({usage['model'] for usage in flat if usage and usage.get('model')}),
        'provider_input_tokens': sum(usage['input_tokens'] for usage in flat) if fully_metered else None,
        'provider_output_tokens': sum(usage['output_tokens'] for usage in flat) if fully_metered else None,
        'average_tokens': mean(sum(usage['input_tokens'] + usage['output_tokens'] for usage in attempt)
                               for attempt in token_rows) if token_rows else None,
        'token_samples': len(token_rows),
        'estimated_model_cost_usd': str(known_cost) if recorded and len(costs) == len(flat) else None,
        'known_estimated_model_cost_usd': str(known_cost),
        'requests_without_cost': len(flat) - len(costs),
    })
    return report


def summarize(directory):
    manifest = json_file(directory / 'manifest.json')
    mode = manifest['execution_mode']
    if mode not in {'offline_fixture', 'live_model'}:
        raise ValueError('Unknown benchmark execution mode.')
    rows = []
    for entry in manifest['entries']:
        path = directory / 'entries' / entry['task_id'] / entry['strategy'] / 'attempt-001' / 'result.json'
        outcome = json_file(path) if path.exists() else {
            'outcome': 'interrupted' if mode == 'live_model' and path.with_name('started.json').exists() else 'not_run',
        }
        rows.append({**outcome, **entry})
    rate = metrics
    ledger = []
    if mode == 'live_model':
        ledger = model_request_rows(directory)
        usage = defaultdict(list)
        for call in ledger:
            usage[(call['task_id'], call['strategy'], call['attempt'])].append(call['usage'])

        def rate(group):
            return live_metrics(group, usage)

    by_strategy = {}
    for strategy in dict.fromkeys(row['strategy'] for row in rows):
        group = [row for row in rows if row['strategy'] == strategy]
        by_strategy[strategy] = {
            **rate(group),
            'by_category': {category: rate([row for row in group if row['category'] == category])
                            for category in sorted({row['category'] for row in group})},
        }
    report = {**rate(rows), 'execution_mode': mode, 'by_strategy': by_strategy}
    if mode == 'live_model':
        report.update(split=manifest['split'], reserved_model_requests_total=len(ledger),
                      max_model_requests=manifest['model']['max_model_requests'])
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runs', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(summarize(args.runs), indent=2))


if __name__ == '__main__':
    main()
