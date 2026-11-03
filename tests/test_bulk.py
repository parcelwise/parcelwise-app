import dataclasses
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.core.config import settings
from app.labels import bulk as bulk_module, carriers
from app.labels.bulk import AllowanceExceeded, BulkItem, BulkNotEnabled, buy_labels_bulk
from app.labels.carriers import CarrierError
from app.labels.rates import Rate
from tests.conftest import FakeCarrier, FakeMerchant, FakeOrder

PRICE = Decimal("5.40")


@pytest.fixture(autouse=True)
def bloom(monkeypatch):
    enable(monkeypatch, {"bloom"})


def enable(monkeypatch, merchants):
    patched = dataclasses.replace(settings, bulk_labels_merchants=frozenset(merchants))
    monkeypatch.setattr(bulk_module, "settings", patched)


def make(n, carrier="usps", rate=None):
    merchant = FakeMerchant()
    merchant.id = "bloom"
    now = datetime.now(timezone.utc)
    return [
        BulkItem(FakeOrder(f"o{i}", merchant), rate or Rate(carrier, "ground", PRICE, now, f"r{i}"), PRICE)
        for i in range(n)
    ]


def run(items, monkeypatch, fake=None, **kw):
    fake = fake or FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    sleeps = []
    kw.setdefault("live_label_ids", set())
    kw.setdefault("labels_remaining", 1000)
    out = buy_labels_bulk(items, batch_id="b1", sleep=sleeps.append, clock=lambda: 0.0, **kw)
    return out, fake, sleeps


def test_buys_each_order_once_in_order_with_stable_keys(monkeypatch):
    out, fake, _ = run(make(3), monkeypatch)
    assert [r.status for r in out] == ["bought"] * 3
    assert fake.bought == ["o0:bulk:b1", "o1:bulk:b1", "o2:bulk:b1"]


def test_throttled_to_forty_a_minute(monkeypatch):
    _, _, sleeps = run(make(3), monkeypatch)
    assert sleeps == [1.5, 1.5]


def test_skips_orders_with_a_live_label(monkeypatch):
    out, fake, _ = run(make(2), monkeypatch, live_label_ids={"o0"})
    assert [(r.order_id, r.status) for r in out] == [("o0", "skipped"), ("o1", "bought")]
    assert out[0].reason == "order already has a label"
    assert fake.bought == ["o1:bulk:b1"]


def test_usps_only(monkeypatch):
    out, fake, _ = run(make(1, carrier="ups"), monkeypatch)
    assert out[0].status == "skipped" and fake.bought == []


def test_keeps_going_after_a_failure(monkeypatch):
    class Flaky(FakeCarrier):
        def buy(self, order, rate, *, idempotency_key):
            if order.id == "o1":
                raise CarrierError("rejected")
            return super().buy(order, rate, idempotency_key=idempotency_key)

    out, fake, _ = run(make(3), monkeypatch, fake=Flaky())
    assert [r.status for r in out] == ["bought", "failed", "bought"]
    assert out[1].reason == "rejected"


def test_stale_quote_is_reported_not_bought(monkeypatch):
    items = make(1)
    items[0].rate = Rate("usps", "ground", PRICE, datetime.now(timezone.utc) - timedelta(minutes=11), "r")
    out, fake, _ = run(items, monkeypatch)
    assert out[0].status == "failed" and fake.bought == []


def test_changed_price_is_not_bought(monkeypatch):
    items = make(1)
    items[0].shown_price = Decimal("4.00")
    out, fake, _ = run(items, monkeypatch)
    assert out[0].status == "failed" and fake.bought == []


def test_off_for_merchants_without_the_flag(monkeypatch):
    enable(monkeypatch, set())
    with pytest.raises(BulkNotEnabled):
        run(make(1), monkeypatch)


def test_batch_over_the_allowance_buys_nothing(monkeypatch):
    fake = FakeCarrier()
    with pytest.raises(AllowanceExceeded) as raised:
        run(make(3), monkeypatch, fake=fake, labels_remaining=2)
    assert raised.value.remaining == 2 and fake.bought == []


def test_skipped_orders_do_not_count_against_the_allowance(monkeypatch):
    out, fake, _ = run(make(3), monkeypatch, live_label_ids={"o0"}, labels_remaining=2)
    assert [r.status for r in out] == ["skipped", "bought", "bought"]
