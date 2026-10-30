from datetime import datetime, timedelta, timezone
from itertools import pairwise
from decimal import Decimal

import pytest

from app.labels import carriers
from app.labels.batch import AllowanceExceeded, BatchItem, Pacer, check_allowance, run_items
from app.labels.carriers import CarrierError
from app.labels.rates import Rate
from tests.conftest import FakeCarrier, FakeOrder


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def rate(minutes_old=0, price="5.40"):
    quoted_at = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
    return Rate("usps", "ground_advantage", Decimal(price), quoted_at, "rate_1")


def item(order_id, **kwargs):
    r = kwargs.pop("rate", None) or rate()
    return BatchItem(7, order_id, r, r.price, **kwargs)


@pytest.fixture
def fake(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    return fake


def run(items, clock=None):
    clock = clock or FakeClock()
    saved = []
    run_items(items, FakeOrder, pacer=Pacer(clock=clock.clock, sleep=clock.sleep), on_item=saved.append)
    return saved


def test_buys_each_order_once_with_its_own_key(fake):
    items = [item("o1"), item("o2"), item("o3")]
    run(items)
    assert fake.bought == ["batch7:o1:1", "batch7:o2:1", "batch7:o3:1"]
    assert [i.status for i in items] == ["bought"] * 3
    assert items[1].tracking_number == "TRK0002"


def test_never_faster_than_forty_a_minute(fake, monkeypatch):
    clock = FakeClock()
    starts = []
    real_buy = fake.buy

    def timed_buy(order, rate, *, idempotency_key):
        starts.append(clock.now)
        return real_buy(order, rate, idempotency_key=idempotency_key)

    monkeypatch.setattr(fake, "buy", timed_buy)
    run([item(f"o{n}") for n in range(200)], clock)
    assert len(starts) == 200
    assert all(b - a >= 1.5 for a, b in pairwise(starts))
    assert sum(1 for t in starts if t < 60) == 40


def test_stops_at_the_first_stale_price(fake):
    items = [item("o1"), item("o2", rate=rate(minutes_old=11)), item("o3"), item("o4", status="bought")]
    saved = run(items)
    assert fake.bought == ["batch7:o1:1"]
    assert [i.status for i in items] == ["bought", "stale", "stale", "bought"]
    assert [i.order_id for i in saved] == ["o1", "o2", "o3"]
    assert not items[1].sent_to_carrier


def test_carrier_failure_is_recorded_and_the_batch_goes_on(fake, monkeypatch):
    real_buy = fake.buy

    def flaky(order, rate, *, idempotency_key):
        if order.id == "o2":
            raise CarrierError("address rejected")
        return real_buy(order, rate, idempotency_key=idempotency_key)

    monkeypatch.setattr(fake, "buy", flaky)
    items = [item("o1"), item("o2"), item("o3")]
    run(items)
    assert [i.status for i in items] == ["bought", "failed", "bought"]
    assert items[1].error == "address rejected"
    assert items[1].sent_to_carrier


def test_requote_bumps_the_attempt_only_if_the_carrier_never_saw_it():
    stale = item("o1", status="stale")
    stale.requote(rate(price="5.60"), Decimal("5.60"))
    assert (stale.status, stale.idempotency_key, stale.shown_price) == ("queued", "batch7:o1:2", Decimal("5.60"))

    failed = item("o2", status="failed", sent_to_carrier=True)
    failed.requote(rate(price="5.60"), Decimal("5.60"))
    assert failed.idempotency_key == "batch7:o2:1"


def test_allowance_blocks_the_whole_batch_up_front():
    check_allowance("starter", 800, 200)
    with pytest.raises(AllowanceExceeded) as error:
        check_allowance("starter", 801, 200)
    assert error.value.remaining == 199
    check_allowance("growth", 10_000, 200)
