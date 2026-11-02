from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.labels import carriers
from app.labels.bulk import CARRIER_FAILED, PRICE_OR_QUOTE_CHANGED, BatchItem, Pacer, run_items
from app.labels.carriers import CarrierError
from app.labels.rates import Rate
from tests.conftest import FakeCarrier, FakeOrder


def _item(order_id, *, age=timedelta(0), price="5.40", shown="5.40"):
    rate = Rate("usps", "ground_advantage", Decimal(price), datetime.now(timezone.utc) - age, "r")
    return BatchItem(FakeOrder(order_id), rate, Decimal(shown), f"batch1:{order_id}")


def _no_wait():
    return Pacer(clock=lambda: 0.0, sleep=lambda s: None)


def test_stale_and_changed_price_items_are_skipped_and_the_rest_are_bought(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    items = [_item("a"), _item("b", age=timedelta(minutes=11)), _item("c", shown="5.00"), _item("d")]
    results = run_items(items, pacer=_no_wait())
    assert [(r.order_id, r.bought, r.reason) for r in results] == [
        ("a", True, ""),
        ("b", False, PRICE_OR_QUOTE_CHANGED),
        ("c", False, PRICE_OR_QUOTE_CHANGED),
        ("d", True, ""),
    ]
    assert fake.bought == ["batch1:a", "batch1:d"]


def test_carrier_error_skips_that_order_and_continues(monkeypatch):
    class Flaky(FakeCarrier):
        def buy(self, order, rate, *, idempotency_key):
            if order.id == "b":
                raise CarrierError("down", retryable=False)
            return super().buy(order, rate, idempotency_key=idempotency_key)

    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: Flaky())
    results = run_items([_item("a"), _item("b"), _item("c")], pacer=_no_wait())
    assert [(r.order_id, r.bought, r.reason) for r in results] == [
        ("a", True, ""),
        ("b", False, CARRIER_FAILED),
        ("c", True, ""),
    ]


def test_items_are_paced(monkeypatch):
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: FakeCarrier())
    now = [0.0]
    slept = []

    def sleep(seconds):
        slept.append(seconds)
        now[0] += seconds

    run_items([_item("a"), _item("b"), _item("c")], pacer=Pacer(clock=lambda: now[0], sleep=sleep))
    assert slept == [1.5, 1.5]
