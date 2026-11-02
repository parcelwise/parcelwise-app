from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal

from app.labels import batch_store, carriers
from app.labels.batch import BOUGHT, OVER_ALLOWANCE, BatchItem, PerMinuteLimiter
from app.labels.rates import Rate
from app.workers import label_worker
from tests.conftest import FakeCarrier, FakeOrder


def test_worker_saves_each_order_then_finishes(monkeypatch):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    now = datetime.now(UTC)
    items = [
        BatchItem(f"o{i}", i, Rate("usps", "ground_advantage", Decimal("5.40"), now, f"r{i}"), Decimal("5.40"))
        for i in range(3)
    ]
    events = []
    monkeypatch.setattr(batch_store, "claim_next_batch", lambda conn: (9, "bloom"))
    monkeypatch.setattr(batch_store, "load_items", lambda conn, batch_id: items)
    monkeypatch.setattr(batch_store, "labels_left_now", lambda conn, merchant_id: 2)
    monkeypatch.setattr(
        batch_store,
        "save_item",
        lambda conn, batch_id, merchant_id, item, label, *, idempotency_key: events.append(
            (item.order_id, item.status, idempotency_key)
        ),
    )
    monkeypatch.setattr(batch_store, "finish_batch", lambda conn, batch_id: events.append(("done", batch_id)))

    @contextmanager
    def tx():
        yield object()

    ran = label_worker.run_once(load_order=FakeOrder, limiter=PerMinuteLimiter({}), tx=tx)
    assert ran
    assert events == [
        ("o0", BOUGHT, "o0:batch:9"),
        ("o1", BOUGHT, "o1:batch:9"),
        ("o2", OVER_ALLOWANCE, "o2:batch:9"),
        ("done", 9),
    ]


def test_worker_idles_on_empty_queue(monkeypatch):
    monkeypatch.setattr(batch_store, "claim_next_batch", lambda conn: None)

    @contextmanager
    def tx():
        yield object()

    assert label_worker.run_once(load_order=FakeOrder, limiter=PerMinuteLimiter({}), tx=tx) is False
