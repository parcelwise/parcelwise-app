from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.labels import carriers
from app.labels.batch import (
    ALREADY_LABELED,
    BOUGHT,
    FAILED,
    NEEDS_PRICE_APPROVAL,
    OVER_ALLOWANCE,
    QUEUED,
    BatchItem,
    PerMinuteLimiter,
    plan_batch,
    run_batch,
    summary,
)
from app.labels.carriers import CarrierError
from app.labels.rates import Rate
from tests.conftest import FakeCarrier, FakeOrder


def make_items(n, *, carrier="usps", quoted_at=None, price="5.40"):
    quoted_at = quoted_at or datetime.now(UTC)
    return [
        BatchItem(f"o{i}", i, Rate(carrier, "ground_advantage", Decimal(price), quoted_at, f"rate_{i}"), Decimal(price))
        for i in range(n)
    ]


class NoLimit(PerMinuteLimiter):
    def __init__(self):
        super().__init__({})


def test_plan_skips_orders_that_already_have_a_live_label():
    items = plan_batch(make_items(3), live_order_ids={"o1"}, plan="growth", used_this_month=0)
    assert [i.status for i in items] == [QUEUED, ALREADY_LABELED, QUEUED]


def test_plan_buys_as_many_as_fit_in_the_order_shown():
    items = make_items(5)
    items.reverse()  # positions, not list order, decide what the merchant saw
    planned = plan_batch(items, live_order_ids={"o0"}, plan="free", used_this_month=48)
    assert [(i.order_id, i.status) for i in planned] == [
        ("o0", ALREADY_LABELED),
        ("o1", QUEUED),
        ("o2", QUEUED),
        ("o3", OVER_ALLOWANCE),
        ("o4", OVER_ALLOWANCE),
    ]


def test_run_buys_each_order_with_its_own_key(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    items = run_batch(7, "m1", make_items(3), load_order=FakeOrder, labels_left=None, limiter=NoLimit())
    assert [i.status for i in items] == [BOUGHT] * 3
    assert fake.bought == ["o0:batch:7", "o1:batch:7", "o2:batch:7"]


def test_run_keeps_going_when_an_order_fails(monkeypatch):
    class FlakyCarrier(FakeCarrier):
        def buy(self, order, rate, *, idempotency_key):
            if order.id == "o1":
                raise CarrierError("address not deliverable")
            return super().buy(order, rate, idempotency_key=idempotency_key)

    fake = FlakyCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    items = run_batch(1, "m1", make_items(3), load_order=FakeOrder, labels_left=None, limiter=NoLimit())
    assert [i.status for i in items] == [BOUGHT, FAILED, BOUGHT]
    assert items[1].error == "address not deliverable"


def test_run_skips_stale_quotes_for_price_approval(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    stale = make_items(1, quoted_at=datetime.now(UTC) - timedelta(minutes=11))
    fresh = make_items(2)[1:]
    items = run_batch(1, "m1", stale + fresh, load_order=FakeOrder, labels_left=None, limiter=NoLimit())
    assert [i.status for i in items] == [NEEDS_PRICE_APPROVAL, BOUGHT]
    assert fake.bought == ["o1:batch:1"]


def test_run_rechecks_the_allowance_left_when_it_starts(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    saved = []
    items = run_batch(
        1,
        "m1",
        make_items(3),
        load_order=FakeOrder,
        labels_left=2,
        limiter=NoLimit(),
        on_item=lambda item, label: saved.append(item.status),
    )
    assert [i.status for i in items] == [BOUGHT, BOUGHT, OVER_ALLOWANCE]
    assert saved == [BOUGHT, BOUGHT, OVER_ALLOWANCE]
    assert summary(items) == {BOUGHT: 2, OVER_ALLOWANCE: 1}


def test_resumed_batch_does_not_rebuy_saved_orders(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    items = make_items(2)
    items[0].status = BOUGHT
    run_batch(1, "m1", items, load_order=FakeOrder, labels_left=None, limiter=NoLimit())
    assert fake.bought == ["o1:batch:1"]


def test_usps_limit_is_40_a_minute_per_merchant():
    clock = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds

    limiter = PerMinuteLimiter(clock=lambda: clock[0], sleep=sleep)
    for _ in range(40):
        limiter.wait("bloom", "usps")
    assert slept == []
    limiter.wait("other-merchant", "usps")  # each merchant has its own window
    assert slept == []
    limiter.wait("bloom", "usps")
    assert slept == [60.0]


def test_other_carriers_are_not_throttled():
    limiter = PerMinuteLimiter(clock=lambda: 0.0, sleep=lambda s: (_ for _ in ()).throw(AssertionError("slept")))
    for _ in range(100):
        limiter.wait("bloom", "ups")
