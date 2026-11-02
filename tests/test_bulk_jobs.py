from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from app.labels import carriers
from app.labels.bulk import (
    ALREADY_LABELED,
    PRICE_OR_QUOTE_CHANGED,
    AllowanceExceeded,
    BatchTooLarge,
    Pacer,
)
from app.labels.bulk_jobs import (
    BulkNotEnabled,
    Quote,
    UnknownOrders,
    batch_progress,
    create_batch,
    idempotency_key,
    work_next_batch,
)
from tests.conftest import FakeCarrier, FakeOrder


class MemoryStore:
    """Same behaviour as PostgresStore, in memory."""

    def __init__(self, *, enabled=True, plan="growth", used=0, orders=(), labeled=()):
        self.merchant = {"plan": plan, "labels_this_month": used, "bulk_labels_enabled": enabled}
        self.orders = set(orders)
        self.labeled = set(labeled)
        self.batches = {}
        self.items = {}
        self.bought_labels = []

    def get_merchant(self, merchant_id):
        return self.merchant

    def unfulfilled_order_ids(self, merchant_id, order_ids):
        return self.orders & set(order_ids)

    def live_label_order_ids(self, order_ids):
        return self.labeled & set(order_ids)

    def create_batch(self, merchant_id, quotes, skipped):
        batch_id = len(self.batches) + 1
        self.batches[batch_id] = {"id": batch_id, "merchant_id": merchant_id, "status": "pending"}
        self.items[batch_id] = [
            {
                "order_id": q.order_id, "carrier": q.carrier, "service": q.service, "rate_id": q.rate_id,
                "price": q.price, "quoted_at": q.quoted_at,
                "status": "skipped" if q.order_id in skipped else "pending",
                "reason": skipped.get(q.order_id, ""), "tracking_number": "",
            }
            for q in quotes
        ]
        return batch_id

    def claim_next_batch(self):
        for b in self.batches.values():
            if b["status"] in ("pending", "running"):
                b["status"] = "running"
                return b
        return None

    def pending_items(self, batch_id):
        return [i for i in self.items[batch_id] if i["status"] == "pending"]

    def _item(self, batch_id, order_id):
        return next(i for i in self.items[batch_id] if i["order_id"] == order_id)

    def record_bought(self, batch_id, merchant_id, label, key):
        self.bought_labels.append((label.order_id, key))
        self.labeled.add(label.order_id)
        self.merchant["labels_this_month"] += 1
        item = self._item(batch_id, label.order_id)
        item.update(status="bought", tracking_number=label.tracking_number)

    def record_skipped(self, batch_id, order_id, reason):
        self._item(batch_id, order_id).update(status="skipped", reason=reason)

    def finish_batch(self, batch_id):
        self.batches[batch_id]["status"] = "done"

    def batch_with_items(self, merchant_id, batch_id):
        if batch_id not in self.batches or self.batches[batch_id]["merchant_id"] != merchant_id:
            raise LookupError(batch_id)
        return self.batches[batch_id], self.items[batch_id]


def _quote(order_id, *, age=timedelta(0), price="5.40"):
    return Quote(order_id, "usps", "ground_advantage", f"r_{order_id}", Decimal(price),
                 datetime.now(timezone.utc) - age)


def _no_wait():
    return Pacer(clock=lambda: 0.0, sleep=lambda s: None)


def _fake_carrier(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    return fake


def test_not_enabled_merchant_is_refused():
    store = MemoryStore(enabled=False, orders={"a"})
    with pytest.raises(BulkNotEnabled):
        create_batch(store, "m1", [_quote("a")])
    assert store.batches == {}


def test_over_200_orders_is_refused_before_anything_is_written():
    ids = [f"o{i}" for i in range(201)]
    store = MemoryStore(orders=ids)
    with pytest.raises(BatchTooLarge):
        create_batch(store, "m1", [_quote(i) for i in ids])
    assert store.batches == {}


def test_orders_that_are_not_the_merchants_are_refused():
    store = MemoryStore(orders={"a"})
    with pytest.raises(UnknownOrders) as err:
        create_batch(store, "m1", [_quote("a"), _quote("zzz")])
    assert err.value.order_ids == {"zzz"}


def test_allowance_counts_only_orders_that_will_be_bought_and_refuses_the_whole_batch():
    store = MemoryStore(plan="free", used=48, orders={"a", "b", "c"}, labeled={"c"})
    create_batch(store, "m1", [_quote("a"), _quote("b"), _quote("c")])  # 2 to buy, 2 left: fine
    store = MemoryStore(plan="free", used=49, orders={"a", "b"})
    with pytest.raises(AllowanceExceeded) as err:
        create_batch(store, "m1", [_quote("a"), _quote("b")])
    assert err.value.remaining == 1
    assert store.batches == {}


def test_already_labeled_orders_are_recorded_as_skipped_and_never_bought(monkeypatch):
    fake = _fake_carrier(monkeypatch)
    store = MemoryStore(orders={"a", "b"}, labeled={"b"})
    summary = create_batch(store, "m1", [_quote("a"), _quote("b")])
    assert summary["skipped"] == [{"order_id": "b", "reason": ALREADY_LABELED}]
    while work_next_batch(store, FakeOrder, pacer=_no_wait()):
        pass
    assert fake.bought == [idempotency_key(1, "a")]
    progress = batch_progress(store, "m1", summary["batch_id"])
    assert progress["status"] == "done"
    assert progress["counts"] == {"bought": 1, "skipped": 1, "pending": 0}


def test_stale_price_is_skipped_reported_and_the_rest_still_buy(monkeypatch):
    fake = _fake_carrier(monkeypatch)
    store = MemoryStore(orders={"a", "b", "c"})
    create_batch(store, "m1", [_quote("a"), _quote("b", age=timedelta(minutes=11)), _quote("c")])
    assert work_next_batch(store, FakeOrder, pacer=_no_wait()) is True
    items = {i["order_id"]: i for i in store.items[1]}
    assert items["a"]["status"] == "bought" and items["c"]["status"] == "bought"
    assert items["b"]["status"] == "skipped" and items["b"]["reason"] == PRICE_OR_QUOTE_CHANGED
    assert fake.bought == [idempotency_key(1, "a"), idempotency_key(1, "c")]
    assert store.merchant["labels_this_month"] == 2


def test_a_restarted_worker_only_buys_what_is_still_pending(monkeypatch):
    fake = _fake_carrier(monkeypatch)
    store = MemoryStore(orders={"a", "b"})
    create_batch(store, "m1", [_quote("a"), _quote("b")])
    store.batches[1]["status"] = "running"  # worker died after buying a
    store.record_bought(1, "m1", type("L", (), {"order_id": "a", "tracking_number": "T1"})(), "k")
    work_next_batch(store, FakeOrder, pacer=_no_wait())
    assert fake.bought == [idempotency_key(1, "b")]
    assert store.batches[1]["status"] == "done"


def test_an_order_labeled_after_the_batch_was_queued_is_not_bought_again(monkeypatch):
    fake = _fake_carrier(monkeypatch)
    store = MemoryStore(orders={"a"})
    create_batch(store, "m1", [_quote("a")])
    store.labeled.add("a")  # bought one at a time in the meantime
    work_next_batch(store, FakeOrder, pacer=_no_wait())
    assert fake.bought == []
    assert store.items[1][0]["reason"] == ALREADY_LABELED


def test_progress_is_not_visible_to_another_merchant():
    store = MemoryStore(orders={"a"})
    summary = create_batch(store, "m1", [_quote("a")])
    with pytest.raises(LookupError):
        batch_progress(store, "other", summary["batch_id"])


def test_no_work_returns_false():
    assert work_next_batch(MemoryStore(), FakeOrder, pacer=_no_wait()) is False


def test_worker_sleeps_when_idle_and_works_when_there_is_a_batch(monkeypatch):
    from app.labels.worker import run_forever

    _fake_carrier(monkeypatch)
    monkeypatch.setattr("app.labels.bulk_jobs.Pacer", lambda: _no_wait())
    store = MemoryStore(orders={"a"})
    create_batch(store, "m1", [_quote("a")])
    sleeps, ticks = [], iter([False, False, True])
    run_forever(store, FakeOrder, idle_seconds=7, sleep=sleeps.append, should_stop=lambda: next(ticks))
    assert store.items[1][0]["status"] == "bought"
    assert sleeps == [7]
