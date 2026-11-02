"""The label-worker against a fake connection that answers the few queries it makes."""

from datetime import datetime, timezone
from decimal import Decimal

from app.labels import carriers
from app.labels.ratelimit import PurchaseRateLimiter
from app.labels.worker import seed_limiter, work_once
from tests.conftest import FakeCarrier, FakeOrder


class Result:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, queued, live_labels=(), closed=(), recent=()):
        self.queued = queued
        self.live_labels = set(live_labels)
        self.closed = set(closed)
        self.recent = list(recent)
        self.writes = []

    def execute(self, sql, params=()):
        if sql.startswith("SELECT batch_id"):
            return Result(list(self.queued))
        if sql.startswith("SELECT order_id FROM labels"):
            return Result([(o,) for o in params[0] if o in self.live_labels])
        if sql.startswith("SELECT status FROM orders"):
            return Result([("cancelled" if params[0] in self.closed else "unfulfilled",)])
        if sql.startswith("SELECT merchant_id, carrier"):
            return Result(self.recent)
        self.writes.append((sql.split()[0] + " " + sql.split()[1], params))
        return Result([])


def row(order_id, merchant="bloom", price="5.40", attempts=0):
    now = datetime.now(timezone.utc)
    return ("b1", order_id, merchant, "usps", "ground_advantage", "r1", Decimal(price), now, Decimal(price), attempts)


def load(conn, order_id):
    return FakeOrder(order_id)


def test_worker_buys_saves_label_and_counts_it(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    conn = FakeConn([row("o1")])
    assert work_once(conn, load_order=load, limiter=PurchaseRateLimiter()) == 0
    assert fake.bought == ["batch:b1:o1:1"]
    kinds = [w[0] for w in conn.writes]
    assert kinds == ["INSERT INTO", "UPDATE merchants", "UPDATE label_batch_items"]
    assert conn.writes[2][1][0] == "bought"


def test_worker_skips_an_order_that_got_a_label_meanwhile(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    conn = FakeConn([row("o1")], live_labels={"o1"})
    work_once(conn, load_order=load, limiter=PurchaseRateLimiter())
    assert fake.bought == []
    assert conn.writes[-1][1][0] == "already_labeled"


def test_worker_moves_on_to_a_merchant_that_is_not_rate_limited(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    limiter = PurchaseRateLimiter(limits={"usps": 1})
    limiter.record("bloom", "usps")
    conn = FakeConn([row("o1", merchant="bloom"), row("o2", merchant="other")])
    work_once(conn, load_order=load, limiter=limiter)
    assert fake.bought == ["batch:b1:o2:1"]


def test_worker_waits_when_every_queued_account_is_at_its_limit(monkeypatch):
    limiter = PurchaseRateLimiter(limits={"usps": 1})
    limiter.record("bloom", "usps")
    conn = FakeConn([row("o1")])
    assert work_once(conn, load_order=load, limiter=limiter) > 0
    assert conn.writes == []


def test_worker_uses_the_next_attempt_key_after_a_merchant_retry(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    conn = FakeConn([row("o1", attempts=1)])
    work_once(conn, load_order=load, limiter=PurchaseRateLimiter())
    assert fake.bought == ["batch:b1:o1:2"]
    assert conn.writes[0][1][-1] == "batch:b1:o1:2"


def _failing(monkeypatch, retryable):
    from app.labels.carriers import CarrierError

    class Failing(FakeCarrier):
        def buy(self, order, rate, *, idempotency_key):
            self.bought.append(idempotency_key)
            raise CarrierError("boom", retryable=retryable)

    fake = Failing()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    return fake


def test_a_timeout_does_not_use_up_the_attempt_so_the_retry_reuses_the_key(monkeypatch):
    _failing(monkeypatch, retryable=True)
    conn = FakeConn([row("o1")])
    work_once(conn, load_order=load, limiter=PurchaseRateLimiter())
    sql_params = conn.writes[-1][1]
    assert sql_params[0] == "failed"
    assert sql_params[3] == 0  # attempts += 0: the next attempt is still 1, key batch:b1:o1:1


def test_any_other_failure_uses_up_the_attempt_so_the_retry_gets_a_new_key(monkeypatch):
    _failing(monkeypatch, retryable=False)
    conn = FakeConn([row("o1")])
    work_once(conn, load_order=load, limiter=PurchaseRateLimiter())
    assert conn.writes[-1][1][3] == 1


def test_worker_records_whether_the_attempt_timed_out(monkeypatch):
    _failing(monkeypatch, retryable=True)
    conn = FakeConn([row("o1")])
    work_once(conn, load_order=load, limiter=PurchaseRateLimiter())
    assert conn.writes[-1][1][4] is True


def test_worker_skips_an_order_cancelled_while_the_batch_ran(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    limiter = PurchaseRateLimiter(limits={"usps": 1})
    conn = FakeConn([row("o1")], closed={"o1"})
    work_once(conn, load_order=load, limiter=limiter)
    assert fake.bought == []
    assert conn.writes[-1][1][0] == "no_longer_unfulfilled"
    # Nothing went to the carrier, so it doesn't count against the rate limit.
    assert limiter.wait_seconds("bloom", "usps") == 0


def test_a_restarted_worker_counts_the_last_minute_of_purchases():
    class Clock:
        now = 1000.0

        def __call__(self):
            return self.now

    clock = Clock()
    limiter = PurchaseRateLimiter(limits={"usps": 2}, clock=clock)
    recent = [("bloom", "usps", 50.0), ("bloom", "usps", 10.0), ("other", "usps", 5.0), ("bloom", "ups", 1.0)]
    seed_limiter(FakeConn([], recent=recent), limiter)
    # Bloom sent 2 in the last minute, so it waits until the older one is a minute old.
    assert limiter.wait_seconds("bloom", "usps") == 10.0
    assert limiter.wait_seconds("other", "usps") == 0
    clock.now += 10.0
    assert limiter.wait_seconds("bloom", "usps") == 0
