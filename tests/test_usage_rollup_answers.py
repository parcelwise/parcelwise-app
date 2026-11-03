from datetime import date

from app.usage import store
from app.usage.daily import ASSISTANT_ANSWERS


class FakeCursor:
    def __init__(self):
        self.statements = []
        self.rowcount = 2

    def execute(self, sql, params=()):
        self.statements.append((sql, params))


def test_rollup_counts_completed_answers_once_per_question_beside_the_attempts(monkeypatch):
    from contextlib import contextmanager

    cur = FakeCursor()

    @contextmanager
    def transaction():
        yield cur

    monkeypatch.setattr(store, "transaction", transaction)
    assert store.UsageStore().rollup_day(date(2026, 12, 1)) == 4
    attempts_sql = cur.statements[1][0]
    answers_sql, params = cur.statements[2]
    assert "COUNT(*)" in attempts_sql and "status <> 'voided'" in attempts_sql
    assert "COUNT(DISTINCT request_id)" in answers_sql
    assert "feature = 'assistant'" in answers_sql and "status = 'completed'" in answers_sql
    assert params[1] == ASSISTANT_ANSWERS
