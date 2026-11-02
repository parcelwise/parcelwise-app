"""Retrying batch orders: a timed-out order keeps its original price (Priya Shah, Raven e270d6d52253)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.labels.batch import NEEDS_REQUOTE, QUEUED, BatchItem, retry_items, timed_out_retry
from app.labels.rates import Rate
from tests.conftest import FakeOrder

NOW = datetime.now(timezone.utc)
ORIGINAL = Rate("usps", "ground_advantage", Decimal("5.40"), NOW, "rate_original")
NEW = Rate("usps", "ground_advantage", Decimal("5.90"), NOW, "rate_new")
EXPIRED = Rate("usps", "ground_advantage", Decimal("5.40"), NOW - timedelta(minutes=11), "rate_original")


def test_timed_out_order_retries_at_its_original_price_not_the_new_one():
    requested = BatchItem(FakeOrder("o1"), NEW, Decimal("5.90"))
    retry = timed_out_retry(requested, BatchItem(FakeOrder("o1"), ORIGINAL, Decimal("5.40")))
    assert retry.rate == ORIGINAL
    assert retry.shown_price == Decimal("5.40")


def test_timed_out_order_whose_quote_expired_needs_a_new_price():
    requested = BatchItem(FakeOrder("o1"), NEW, Decimal("5.90"))
    assert timed_out_retry(requested, BatchItem(FakeOrder("o1"), EXPIRED, Decimal("5.40"))) is None


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0]


class RetryConn:
    """Answers the queries retry_items makes for batch b1, merchant bloom; records every UPDATE."""

    def __init__(self, stored):
        self.stored = stored  # order_id -> (status, timed_out, rate, shown_price)
        self.updates = []

    def execute(self, sql, params=()):
        if sql.startswith("SELECT order_id, status, timed_out"):
            return Result(
                [
                    (o, st, to, r.carrier, r.service, r.rate_id, r.price, r.quoted_at, shown)
                    for o, (st, to, r, shown) in self.stored.items()
                    if o in params[2]
                ]
            )
        if sql.startswith("SELECT plan"):
            return Result([("growth", 0)])
        if sql.startswith("SELECT count(*)"):
            return Result([(0,)])
        if sql.startswith("SELECT id, status FROM orders"):
            return Result([(o, "unfulfilled") for o in params[1]])
        if sql.startswith("SELECT"):
            return Result([])
        self.updates.append((sql, params))
        return Result([])


def test_retry_requeues_a_timed_out_order_at_its_stored_price():
    conn = RetryConn({"o1": ("failed", True, ORIGINAL, Decimal("5.40"))})
    retry_items(conn, "bloom", "b1", [BatchItem(FakeOrder("o1"), NEW, Decimal("5.90"))])
    ((_sql, params),) = conn.updates
    assert params[0] == QUEUED
    assert params[3] == "rate_original" and params[4] == Decimal("5.40") and params[6] == Decimal("5.40")


def test_retry_of_a_timed_out_order_with_an_expired_quote_asks_for_a_new_price_and_a_new_key():
    conn = RetryConn({"o1": ("failed", True, EXPIRED, Decimal("5.40"))})
    retry_items(conn, "bloom", "b1", [BatchItem(FakeOrder("o1"), NEW, Decimal("5.90"))])
    ((sql, params),) = conn.updates
    assert params[0] == NEEDS_REQUOTE
    assert "timed_out = false" in sql and "attempts = attempts + 1" in sql


def test_retry_of_any_other_failure_uses_the_newly_approved_price():
    conn = RetryConn({"o1": ("failed", False, ORIGINAL, Decimal("5.40"))})
    retry_items(conn, "bloom", "b1", [BatchItem(FakeOrder("o1"), NEW, Decimal("5.90"))])
    ((_sql, params),) = conn.updates
    assert params[0] == QUEUED and params[3] == "rate_new" and params[6] == Decimal("5.90")
