"""Durable request accounting for the model-backed benchmark."""

from contextlib import closing, contextmanager
import json
import sqlite3
from unittest.mock import patch

from gradmatch.agent import BudgetLimit
from gradmatch.providers import OpenAIProvider


LEDGER_FILE = 'model-requests.sqlite'
USAGE_FIELDS = (
    'call_id', 'response_id', 'model', 'status', 'input_tokens', 'output_tokens',
    'cached_input_tokens', 'reasoning_tokens', 'estimated_cost_usd',
)


class RequestLedger:
    def __init__(self, db, maximum):
        self.db = db
        self.maximum = maximum
        with db:
            db.execute('''CREATE TABLE IF NOT EXISTS model_requests (
                id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, strategy TEXT NOT NULL,
                attempt INTEGER NOT NULL, purpose TEXT NOT NULL, usage_json TEXT
            )''')

    def used(self):
        return self.db.execute('SELECT count(*) FROM model_requests').fetchone()[0]

    @contextmanager
    def capture(self, task_id, strategy, attempt):
        generate = OpenAIProvider.generate

        def metered(provider, output_type, purpose, payload, session):
            # The run directory is locked by the scheduler. Commit before transport
            # so a dropped process cannot restore an uncertain request to the budget.
            with self.db:
                if self.used() >= self.maximum:
                    raise BudgetLimit('BENCHMARK_MODEL_LIMIT')
                reservation = self.db.execute(
                    'INSERT INTO model_requests (task_id, strategy, attempt, purpose) VALUES (?, ?, ?, ?)',
                    (task_id, strategy, attempt, purpose),
                ).lastrowid
            start = len(session.usage)
            try:
                return generate(provider, output_type, purpose, payload, session)
            finally:
                if len(session.usage) > start:
                    usage = {key: session.usage[start].get(key) for key in USAGE_FIELDS}
                    with self.db:
                        self.db.execute('UPDATE model_requests SET usage_json = ? WHERE id = ?',
                                        (json.dumps(usage), reservation))

        with patch.object(OpenAIProvider, 'generate', metered):
            yield


def model_request_rows(directory):
    path = directory / LEDGER_FILE
    if not path.exists():
        if any(directory.glob('entries/*/*/attempt-*')):
            raise ValueError('The model request ledger is missing for an existing run.')
        return []
    with closing(sqlite3.connect(f'{path.resolve().as_uri()}?mode=ro', uri=True)) as db:
        rows = db.execute('SELECT task_id, strategy, attempt, usage_json FROM model_requests ORDER BY id').fetchall()
    return [
        {'task_id': task, 'strategy': strategy, 'attempt': attempt,
         'usage': json.loads(usage) if usage is not None else None}
        for task, strategy, attempt, usage in rows
    ]
