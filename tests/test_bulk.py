from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.labels import carriers
from app.labels.bulk import AllowanceExceeded, BulkItem, buy_labels, check_allowance, start_bulk_purchase
from app.labels.carriers import CarrierError
from app.labels.rates import Rate
from tests.conftest import FakeCarrier, FakeOrder


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


@pytest.fixture
def fake(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    return fake


def items(n, rate):
    return [BulkItem(FakeOrder(f"o{i}"), rate, rate.price) for i in range(n)]


def test_one_purchase_per_order_with_its_own_key(fake, fresh_rate):
    clock = FakeClock()
    result = buy_labels(items(3, fresh_rate), batch_id="b1", sleep=clock.sleep, clock=clock)
    assert fake.bought == ["b1:o0", "b1:o1", "b1:o2"]
    assert [label.order_id for label in result.bought] == ["o0", "o1", "o2"]


def test_at_most_forty_purchases_a_minute(fake, fresh_rate):
    clock = FakeClock()
    buy_labels(items(41, fresh_rate), batch_id="b1", sleep=clock.sleep, clock=clock)
    assert clock.now >= 60


def test_stale_and_changed_prices_are_skipped_not_bought(fake, fresh_rate):
    stale = Rate("usps", "ground_advantage", Decimal("5.40"), datetime.now(timezone.utc) - timedelta(minutes=11))
    batch = [
        BulkItem(FakeOrder("fresh"), fresh_rate, Decimal("5.40")),
        BulkItem(FakeOrder("stale"), stale, Decimal("5.40")),
        BulkItem(FakeOrder("changed"), fresh_rate, Decimal("4.90")),
    ]
    clock = FakeClock()
    result = buy_labels(batch, batch_id="b1", sleep=clock.sleep, clock=clock)
    assert fake.bought == ["b1:fresh"]
    assert result.stale == ["stale", "changed"]


def test_keeps_going_past_failures(monkeypatch, fresh_rate):
    class Flaky(FakeCarrier):
        def buy(self, order, rate, *, idempotency_key):
            if order.id == "o1":
                raise CarrierError("address invalid")
            if order.id == "o2":
                raise KeyError("usps")
            return super().buy(order, rate, idempotency_key=idempotency_key)

    flaky = Flaky()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: flaky)
    clock = FakeClock()
    result = buy_labels(items(4, fresh_rate), batch_id="b1", sleep=clock.sleep, clock=clock)
    assert [label.order_id for label in result.bought] == ["o0", "o3"]
    assert result.failed == {"o1": "address invalid", "o2": "'usps'"}


class RecordingConn:
    def __init__(self):
        self.statements = []

    def execute(self, sql, params=()):
        self.statements.append((sql, params))


def test_batch_over_allowance_is_refused_up_front(fresh_rate):
    conn = RecordingConn()
    with pytest.raises(AllowanceExceeded) as refused:
        start_bulk_purchase(
            conn, items(200, fresh_rate), batch_id="b1", merchant_id="m1", plan="starter", used_this_month=900
        )
    assert refused.value.labels_left == 100
    assert conn.statements == []


def test_queued_batch_keeps_the_price_the_merchant_saw(fresh_rate):
    conn = RecordingConn()
    start_bulk_purchase(conn, items(2, fresh_rate), batch_id="b1", merchant_id="m1", plan="growth", used_this_month=0)
    assert conn.statements[0][1] == ("b1", "m1")
    assert [params[2] for _, params in conn.statements[1:]] == ["o0", "o1"]
    assert all(params[-1] == Decimal("5.40") for _, params in conn.statements[1:])


def test_allowance_allows_exactly_the_limit_and_unlimited_plans():
    check_allowance("starter", 800, 200)
    check_allowance("growth", 10_000, 200)
