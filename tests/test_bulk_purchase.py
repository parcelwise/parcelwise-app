from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.labels import carriers
from app.labels.bulk import (
    USPS_BULK_PER_MINUTE,
    BulkItem,
    buy_all,
    carrier_pacer,
    idempotency_key,
    per_minute_pacer,
    plan_bulk,
)
from app.labels.carriers import CarrierError
from app.labels.purchase import StaleRateError
from app.labels.rates import Rate
from tests.conftest import FakeCarrier, FakeOrder

PRICE = Decimal("5.40")


def items(n, rate, price=PRICE):
    return [BulkItem(FakeOrder(f"o{i}"), rate, price) for i in range(n)]


def ids(batch):
    return [item.order.id for item in batch]


@pytest.fixture
def fake(monkeypatch):
    carrier = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: carrier)
    return carrier


def no_pace(carrier):
    pass


# Planning: what the confirm step shows.


def test_orders_with_a_live_label_are_left_out_and_listed(fresh_rate):
    plan = plan_bulk(
        items(3, fresh_rate), has_live_label=lambda order: order.id == "o1", plan="growth", used_this_month=0
    )
    assert ids(plan.to_buy) == ["o0", "o2"]
    assert ids(plan.already_labelled) == ["o1"]


def test_over_allowance_buys_what_fits_in_the_order_shown(fresh_rate):
    plan = plan_bulk(items(5, fresh_rate), has_live_label=lambda order: False, plan="free", used_this_month=47)
    assert plan.remaining == 3
    assert ids(plan.to_buy) == ["o0", "o1", "o2"]
    assert ids(plan.over_allowance) == ["o3", "o4"]


def test_already_labelled_orders_do_not_use_up_allowance(fresh_rate):
    plan = plan_bulk(
        items(4, fresh_rate), has_live_label=lambda order: order.id == "o0", plan="free", used_this_month=48
    )
    assert ids(plan.to_buy) == ["o1", "o2"]
    assert ids(plan.over_allowance) == ["o3"]


def test_allowance_already_used_up_buys_nothing(fresh_rate):
    plan = plan_bulk(items(2, fresh_rate), has_live_label=lambda order: False, plan="free", used_this_month=60)
    assert plan.remaining == 0
    assert plan.to_buy == []
    assert ids(plan.over_allowance) == ["o0", "o1"]


def test_unlimited_plan_buys_everything(fresh_rate):
    plan = plan_bulk(items(300, fresh_rate), has_live_label=lambda order: False, plan="growth", used_this_month=9999)
    assert len(plan.to_buy) == 300
    assert plan.over_allowance == []
    assert plan.remaining is None


def test_total_is_a_decimal_sum_of_what_will_be_bought(fresh_rate):
    plan = plan_bulk(
        items(3, fresh_rate, Decimal("0.10")), has_live_label=lambda order: False, plan="free", used_this_month=48
    )
    assert plan.total == Decimal("0.20")


# Buying.


def test_each_order_is_bought_once_with_its_own_key(fake, fresh_rate):
    result = buy_all(items(3, fresh_rate), job_id="j1", pace=no_pace)
    assert fake.bought == ["bulk:j1:o0", "bulk:j1:o1", "bulk:j1:o2"]
    assert [label.order_id for label in result.bought] == ["o0", "o1", "o2"]


def test_key_is_stable_for_a_retry_of_the_same_job():
    assert idempotency_key("j1", "o7") == idempotency_key("j1", "o7")
    assert idempotency_key("j1", "o7") != idempotency_key("j2", "o7")


class FailsOn(FakeCarrier):
    def __init__(self, order_id):
        super().__init__()
        self.order_id = order_id

    def buy(self, order, rate, *, idempotency_key):
        if order.id == self.order_id:
            raise CarrierError("bad address")
        return super().buy(order, rate, idempotency_key=idempotency_key)


def test_a_failure_is_reported_and_the_rest_are_still_bought(monkeypatch, fresh_rate):
    carrier = FailsOn("o1")
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: carrier)
    result = buy_all(items(3, fresh_rate), job_id="j1", pace=no_pace)
    assert [label.order_id for label in result.bought] == ["o0", "o2"]
    assert [order_id for order_id, _ in result.failed] == ["o1"]


def test_stale_quote_is_skipped_for_the_merchant_to_approve(fake):
    stale = Rate("usps", "ground_advantage", PRICE, datetime.now(timezone.utc) - timedelta(minutes=11), "r")
    result = buy_all(items(2, stale), job_id="j1", pace=no_pace)
    assert fake.bought == []
    assert result.needs_approval == ["o0", "o1"]


def test_changed_price_is_skipped_for_the_merchant_to_approve(fake, fresh_rate):
    result = buy_all(items(1, fresh_rate, Decimal("4.99")), job_id="j1", pace=no_pace)
    assert fake.bought == []
    assert result.needs_approval == ["o0"]


def test_on_result_is_told_about_every_order(monkeypatch, fresh_rate):
    carrier = FailsOn("o1")
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: carrier)
    seen = []
    buy_all(items(3, fresh_rate), job_id="j1", pace=no_pace, on_result=lambda item, out: seen.append(type(out)))
    assert [t.__name__ for t in seen] == ["Label", "CarrierError", "Label"]


def test_pace_is_called_with_the_carrier_before_every_purchase(fake, fresh_rate):
    calls = []
    buy_all(items(3, fresh_rate), job_id="j1", pace=lambda carrier: calls.append((carrier, len(fake.bought))))
    assert calls == [("usps", 0), ("usps", 1), ("usps", 2)]


def test_stale_rate_error_is_not_a_carrier_error():
    # buy_all relies on this to tell "needs approval" apart from a carrier failure.
    assert not issubclass(StaleRateError, CarrierError)


# Pacing.


def test_usps_bulk_limit_is_40_a_minute():
    assert USPS_BULK_PER_MINUTE == 40


def fake_time():
    now = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    return now, slept, sleep


def test_pacer_keeps_to_the_limit_in_any_minute():
    now, slept, sleep = fake_time()
    pace = per_minute_pacer(40, clock=lambda: now[0], sleep=sleep)
    starts = []
    for _ in range(200):
        pace()
        starts.append(now[0])
    assert slept[0] == pytest.approx(1.5)
    for first in range(len(starts)):
        in_window = [t for t in starts[first:] if t < starts[first] + 60.0]
        assert len(in_window) <= 40


def test_pacer_does_not_sleep_when_calls_are_already_slow():
    now, slept, sleep = fake_time()
    pace = per_minute_pacer(40, clock=lambda: now[0], sleep=sleep)
    pace()
    now[0] += 5
    pace()
    assert slept == []


def test_carrier_pacer_only_slows_usps():
    now, slept, sleep = fake_time()
    pace = carrier_pacer(clock=lambda: now[0], sleep=sleep)
    for _ in range(5):
        pace("ups")
    assert slept == []
    pace("usps")
    pace("usps")
    assert slept == [pytest.approx(1.5)]
