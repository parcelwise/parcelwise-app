"""The worker's job loop, with an in-memory stand-in for the job tables. No database."""

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from app.labels import bulk_jobs, carriers, worker
from app.labels.bulk_jobs import Selection
from app.labels.carriers import CarrierError
from tests.conftest import FakeCarrier, FakeOrder


class FailsOn(FakeCarrier):
    def __init__(self, order_id):
        super().__init__()
        self.order_id = order_id

    def buy(self, order, rate, *, idempotency_key):
        if order.id == self.order_id:
            raise CarrierError("bad address")
        return super().buy(order, rate, idempotency_key=idempotency_key)


def selection(order_id, *, minutes_old=0, price="5.40"):
    quoted = datetime.now(timezone.utc) - timedelta(minutes=minutes_old)
    return Selection(order_id, "usps", "ground_advantage", f"rate_{order_id}", quoted, Decimal(price))


def fake_store(monkeypatch, jobs, labelled=()):
    """jobs: {job_id: (merchant_id, [Selection])}. Replaces the SQL in bulk_jobs with dict operations."""
    state = {"queued": list(jobs), "outcomes": {}, "done": [], "transactions": 0, "labelled": set(labelled)}

    def claim(conn):
        if not state["queued"]:
            return None
        job_id = state["queued"].pop(0)
        return job_id, jobs[job_id][0]

    def pending(conn, job_id):
        recorded = state["outcomes"].get(job_id, {})
        return [(pos, sel) for pos, sel in enumerate(jobs[job_id][1]) if pos not in recorded]

    def record(conn, job_id, position, merchant_id, outcome):
        state["outcomes"].setdefault(job_id, {})[position] = type(outcome).__name__

    monkeypatch.setattr(bulk_jobs, "claim_next_job", claim)
    monkeypatch.setattr(bulk_jobs, "pending_items", pending)
    monkeypatch.setattr(bulk_jobs, "record_outcome", record)
    monkeypatch.setattr(bulk_jobs, "finish_job", lambda conn, job_id: state["done"].append(job_id))
    monkeypatch.setattr(bulk_jobs, "order_has_live_label", lambda conn, order_id: order_id in state["labelled"])

    @contextmanager
    def transaction():
        state["transactions"] += 1
        yield object()

    return state, transaction


def load_order(conn, order_id):
    return FakeOrder(order_id)


def test_worker_runs_a_job_and_saves_every_outcome(monkeypatch):
    carrier = FailsOn("b")
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: carrier)
    state, transaction = fake_store(
        monkeypatch, {7: ("m1", [selection("a"), selection("b"), selection("c", minutes_old=11)])}
    )
    assert worker.run_once(transaction, load_order=load_order, pace=lambda carrier: None)
    assert state["outcomes"][7] == {0: "Label", 1: "CarrierError", 2: "StaleRateError"}
    assert state["done"] == [7]
    assert carrier.bought == ["bulk:7:a"]


def test_worker_skips_items_already_recorded_when_a_job_is_picked_up_again(monkeypatch):
    carrier = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: carrier)
    state, transaction = fake_store(monkeypatch, {7: ("m1", [selection("a"), selection("b")])})
    state["outcomes"][7] = {0: "Label"}
    worker.run_once(transaction, load_order=load_order, pace=lambda carrier: None)
    assert carrier.bought == ["bulk:7:b"]


def test_worker_does_not_buy_an_order_labelled_after_the_job_was_queued(monkeypatch):
    carrier = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: carrier)
    state, transaction = fake_store(monkeypatch, {7: ("m1", [selection("a"), selection("b")])}, labelled={"a"})
    worker.run_once(transaction, load_order=load_order, pace=lambda carrier: None)
    assert carrier.bought == ["bulk:7:b"]
    assert state["outcomes"][7] == {0: "AlreadyLabelled", 1: "Label"}


def test_worker_says_when_there_is_nothing_to_do(monkeypatch):
    state, transaction = fake_store(monkeypatch, {})
    assert worker.run_once(transaction, load_order=load_order, pace=lambda carrier: None) is False


def test_worker_paces_every_purchase(monkeypatch):
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: FakeCarrier())
    state, transaction = fake_store(monkeypatch, {1: ("m1", [selection("a"), selection("b")])})
    paced = []
    worker.run_once(transaction, load_order=load_order, pace=paced.append)
    assert paced == ["usps", "usps"]


class FakeConn:
    """Answers the queries _plan makes: the merchant's plan, labels used this month, orders waiting in other
    jobs, live labels."""

    def __init__(self, *, plan, used, queued, labelled):
        self.answers = {
            "FROM merchants": [(plan,)],
            "count(*)": [(used,)],
            "FROM bulk_label_job_items": queued,
            "FROM labels": labelled,
        }
        self.params = []
        self.sql = []

    def execute(self, sql, params=()):
        self.sql.append(sql)
        self.params.append(params)
        rows = next(rows for key, rows in self.answers.items() if key in sql)
        return type("Cursor", (), {"fetchone": lambda _: rows[0], "fetchall": lambda _: rows})()


def test_orders_waiting_in_another_job_count_as_labelled_and_used():
    conn = FakeConn(plan="free", used=40, queued=[("a",), ("x",)], labelled=[("b",)])
    plan = bulk_jobs.preview(conn, "m1", [selection(o) for o in ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j"]])
    assert plan["alreadyLabelled"] == ["a", "b"]
    assert plan["remaining"] == 8  # 50 - 40 bought - 2 still waiting in another job
    assert plan["toBuy"] == ["c", "d", "e", "f", "g", "h", "i", "j"]
    assert plan["overAllowance"] == []


def test_enqueue_locks_the_merchant_row_but_preview_does_not():
    conn = FakeConn(plan="growth", used=0, queued=[], labelled=[])
    bulk_jobs.preview(conn, "m1", [selection("a")])
    assert "FOR UPDATE" not in conn.sql[0]
    conn = FakeConn(plan="growth", used=0, queued=[], labelled=[])
    conn.answers["INSERT INTO bulk_label_jobs"] = [(9,)]
    conn.answers["INSERT INTO bulk_label_job_items"] = []
    result = bulk_jobs.enqueue(conn, "m1", [selection("a")])
    assert "FOR UPDATE" in conn.sql[0]
    assert result["jobId"] == 9 and result["toBuy"] == ["a"]


def test_used_this_month_counts_every_live_label_bought_this_calendar_month():
    # Single and bulk labels both live in the labels table; voided ones don't count (decision 22d823b40cb3).
    conn = FakeConn(plan="free", used=49, queued=[], labelled=[])
    plan = bulk_jobs.preview(conn, "m1", [selection("a"), selection("b")])
    used_sql = next(sql for sql in conn.sql if "count(*)" in sql)
    assert "FROM labels" in used_sql
    assert "voided_at IS NULL" in used_sql
    assert "date_trunc('month', now())" in used_sql
    assert "labels_this_month" not in " ".join(conn.sql)
    assert plan["toBuy"] == ["a"] and plan["overAllowance"] == ["b"]


def test_a_bought_label_is_not_also_added_to_a_counter():
    conn = FakeConn(plan="free", used=0, queued=[], labelled=[])
    conn.answers = {"INSERT INTO labels": [(5,)], "UPDATE bulk_label_job_items": []}
    label = bulk_jobs.Label("a", "usps", "9400", bulk_jobs.Decimal("5.40"), "https://x")
    bulk_jobs.record_outcome(conn, 7, 0, "m1", label)
    assert not any("labels_this_month" in sql for sql in conn.sql)
