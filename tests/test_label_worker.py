from app.labels import carriers
from app.labels.worker import run_batch
from tests.conftest import FakeCarrier, FakeOrder


class FakeStore:
    def __init__(self, rate, order_ids):
        self.rows = [
            (order_id, rate.carrier, rate.service, rate.price, rate.quoted_at, rate.rate_id, rate.price)
            for order_id in order_ids
        ]
        self.recorded = []
        self.finished = []

    def pending_items(self, batch_id):
        done = {order_id for order_id, _ in self.recorded}
        return [row for row in self.rows if row[0] not in done]

    def record(self, batch_id, order_id, status, detail):
        self.recorded.append((order_id, status))

    def finish(self, batch_id):
        self.finished.append(batch_id)


def no_wait(seconds):
    pass


def test_worker_records_each_order_and_finishes(monkeypatch, fresh_rate):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    store = FakeStore(fresh_rate, ["o1", "o2"])
    run_batch(store, "b1", load_order=FakeOrder, sleep=no_wait)
    assert store.recorded == [("o1", "bought"), ("o2", "bought")]
    assert store.finished == ["b1"]
    assert fake.bought == ["b1:o1", "b1:o2"]


def test_rerun_after_restart_only_buys_what_is_left_with_the_same_keys(monkeypatch, fresh_rate):
    fake = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: fake)
    store = FakeStore(fresh_rate, ["o1", "o2"])
    store.recorded.append(("o1", "bought"))
    run_batch(store, "b1", load_order=FakeOrder, sleep=no_wait)
    assert fake.bought == ["b1:o2"]
