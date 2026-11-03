import json
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.labels import carriers
from app.labels.bulk import AllowanceExceeded, BulkTooLarge
from app.labels.bulk_jobs import (
    BulkAlreadyRunning,
    JobDeps,
    SelectedLine,
    get_job,
    latest_job,
    run_next_job,
    start_bulk_buy,
    work,
)
from app.labels.purchase import Label
from app.labels.rates import Rate
from tests.conftest import FakeCarrier, FakeOrder


class Result:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class FakeJobsDb:
    """Stands in for the bulk_label_jobs table: the statements bulk_jobs.py sends, and the pending-per-merchant index."""

    def __init__(self):
        self.jobs = {}  # id -> dict, in insert order
        self.locked = set()

    def execute(self, sql, params=()):
        if sql.startswith("INSERT INTO bulk_label_jobs"):
            job_id, merchant_id, lines = params
            pending = any(j["merchant_id"] == merchant_id and j["status"] == "pending" for j in self.jobs.values())
            if job_id in self.jobs or pending:
                return Result(None)
            self.jobs[job_id] = {
                "merchant_id": merchant_id,
                "status": "pending",
                "lines": lines,
                "outcomes": None,
                "reason": "",
            }
            return Result((job_id,))
        if "FOR UPDATE SKIP LOCKED" in sql:
            for job_id, job in self.jobs.items():
                if job["status"] == "pending" and job_id not in self.locked:
                    self.locked.add(job_id)
                    return Result((job_id, job["merchant_id"], job["lines"]))
            return Result(None)
        if sql.startswith("UPDATE bulk_label_jobs"):
            status, outcomes, reason, job_id = params
            self.jobs[job_id].update(status=status, outcomes=outcomes, reason=reason)
            return Result(None)
        if "WHERE id = %s AND merchant_id = %s" in sql:
            job_id, merchant_id = params
            job = self.jobs.get(job_id)
            return Result(self._row(job_id) if job and job["merchant_id"] == merchant_id else None)
        if "ORDER BY created_at DESC LIMIT 1" in sql:
            (merchant_id,) = params
            mine = [job_id for job_id, job in self.jobs.items() if job["merchant_id"] == merchant_id]
            return Result(self._row(mine[-1]) if mine else None)
        raise AssertionError(f"unexpected SQL: {sql}")

    def _row(self, job_id):
        job = self.jobs[job_id]
        return (job_id, job["status"], job["outcomes"], job["reason"], len(json.loads(job["lines"])))


def _line(order_id, price="5.40", carrier="usps", age=timedelta(0)):
    rate = Rate(carrier, "ground_advantage", Decimal(price), datetime.now(UTC) - age, f"rate_{order_id}")
    return SelectedLine(order_id, rate, Decimal(price))


@pytest.fixture
def fake(monkeypatch):
    carrier = FakeCarrier()
    monkeypatch.setitem(carriers.CARRIERS, "usps", lambda account: carrier)
    return carrier


def deps(plan="growth", used=0, orders=None, live=None):
    known = orders if orders is not None else None

    def load_order(merchant_id, order_id):
        if merchant_id != "m1" or (known is not None and order_id not in known):
            return None
        return FakeOrder(order_id)

    return JobDeps(
        load_order=load_order,
        plan_and_usage=lambda merchant_id: (plan, used),
        live_label=lambda order: (live or {}).get(order.id),
        sleep=lambda seconds: None,
    )


def test_starting_a_bulk_buy_queues_it_and_buys_nothing(fake):
    db = FakeJobsDb()
    job = start_bulk_buy(db, "m1", "b1", [_line("o1"), _line("o2")], plan="growth", used_this_month=0)
    assert fake.bought == []
    assert (
        job == get_job(db, "m1", "b1") == {"id": "b1", "status": "pending", "outcomes": None, "reason": "", "count": 2}
    )


def test_sending_the_same_batch_again_returns_the_same_job():
    db = FakeJobsDb()
    start_bulk_buy(db, "m1", "b1", [_line("o1")], plan="growth", used_this_month=0)
    assert start_bulk_buy(db, "m1", "b1", [_line("o1")], plan="growth", used_this_month=0)["id"] == "b1"
    assert list(db.jobs) == ["b1"]


def test_a_second_bulk_buy_while_one_is_pending_is_refused():
    db = FakeJobsDb()
    start_bulk_buy(db, "m1", "b1", [_line("o1")], plan="growth", used_this_month=0)
    with pytest.raises(BulkAlreadyRunning):
        start_bulk_buy(db, "m1", "b2", [_line("o2")], plan="growth", used_this_month=0)
    start_bulk_buy(db, "m2", "b3", [_line("o3")], plan="growth", used_this_month=0)  # other merchants are not blocked


def test_batches_that_will_be_refused_are_refused_before_they_are_queued():
    db = FakeJobsDb()
    with pytest.raises(BulkTooLarge):
        start_bulk_buy(db, "m1", "b1", [_line(f"o{i}") for i in range(201)], plan="growth", used_this_month=0)
    with pytest.raises(AllowanceExceeded):
        start_bulk_buy(db, "m1", "b1", [_line("o1"), _line("o2")], plan="free", used_this_month=49)
    assert db.jobs == {}


def test_ups_orders_are_queued_and_then_skipped_with_a_reason(fake):
    db = FakeJobsDb()
    start_bulk_buy(db, "m1", "b1", [_line("o1"), _line("o2", carrier="ups")], plan="growth", used_this_month=0)
    run_next_job(db, deps())
    assert [o["status"] for o in get_job(db, "m1", "b1")["outcomes"]] == ["bought", "skipped"]
    assert fake.bought == ["bulk:b1:o1"]


def test_the_worker_buys_each_order_with_the_batch_id_in_its_key_and_records_outcomes(fake):
    db = FakeJobsDb()
    existing = Label("o2", "usps", "TRK-OLD", Decimal("5.40"), "https://labels.test/o2.pdf")
    start_bulk_buy(db, "m1", "b1", [_line("o1"), _line("o2"), _line("o3")], plan="growth", used_this_month=0)
    assert run_next_job(db, deps(live={"o2": existing})) == "b1"
    assert fake.bought == ["bulk:b1:o1", "bulk:b1:o3"]
    job = get_job(db, "m1", "b1")
    assert job["status"] == "done"
    assert [(o["order_id"], o["status"]) for o in job["outcomes"]] == [
        ("o1", "bought"),
        ("o2", "reprint"),
        ("o3", "bought"),
    ]
    assert job["outcomes"][0]["label"]["price"] == "5.40"


def test_an_order_the_merchant_does_not_have_is_reported_not_bought(fake):
    db = FakeJobsDb()
    start_bulk_buy(db, "m1", "b1", [_line("o1"), _line("gone")], plan="growth", used_this_month=0)
    run_next_job(db, deps(orders={"o1"}))
    job = get_job(db, "m1", "b1")
    assert [(o["order_id"], o["status"], o["reason"]) for o in job["outcomes"]] == [
        ("o1", "bought", ""),
        ("gone", "failed", "order not found"),
    ]
    assert fake.bought == ["bulk:b1:o1"]


def test_a_quote_that_went_stale_before_the_job_ran_is_skipped(fake):
    db = FakeJobsDb()
    start_bulk_buy(
        db, "m1", "b1", [_line("o1", age=timedelta(minutes=11)), _line("o2")], plan="growth", used_this_month=0
    )
    run_next_job(db, deps())
    assert [o["status"] for o in get_job(db, "m1", "b1")["outcomes"]] == ["stale", "bought"]


def test_usage_that_grew_after_queueing_refuses_the_whole_job(fake):
    db = FakeJobsDb()
    start_bulk_buy(db, "m1", "b1", [_line("o1"), _line("o2")], plan="free", used_this_month=40)
    run_next_job(db, deps(plan="free", used=49))
    job = get_job(db, "m1", "b1")
    assert job["status"] == "refused"
    assert "1 labels left" in job["reason"]
    assert fake.bought == []


def test_a_finished_job_frees_the_merchant_for_the_next_one(fake):
    db = FakeJobsDb()
    start_bulk_buy(db, "m1", "b1", [_line("o1")], plan="growth", used_this_month=0)
    run_next_job(db, deps())
    assert start_bulk_buy(db, "m1", "b2", [_line("o2")], plan="growth", used_this_month=0)["id"] == "b2"
    assert latest_job(db, "m1")["id"] == "b2"


def test_a_job_another_worker_holds_is_not_claimed_twice(fake):
    db = FakeJobsDb()
    start_bulk_buy(db, "m1", "b1", [_line("o1")], plan="growth", used_this_month=0)
    db.locked.add("b1")
    assert run_next_job(db, deps()) is None
    assert fake.bought == []


def test_a_job_rerun_after_a_crash_reuses_the_same_keys(fake):
    db = FakeJobsDb()
    start_bulk_buy(db, "m1", "b1", [_line("o1")], plan="growth", used_this_month=0)
    run_next_job(db, deps())
    db.jobs["b1"]["status"] = "pending"  # as if the worker died before committing
    db.locked.clear()
    run_next_job(db, deps())
    assert fake.bought == ["bulk:b1:o1", "bulk:b1:o1"]  # same key both times: the carrier returns the same label


def test_latest_job_and_get_job_only_show_the_merchants_own_jobs():
    db = FakeJobsDb()
    start_bulk_buy(db, "m2", "b1", [_line("o1")], plan="growth", used_this_month=0)
    assert get_job(db, "m1", "b1") is None
    assert latest_job(db, "m1") is None


def test_the_worker_rests_when_nothing_waits_and_stops_when_told(fake):
    db = FakeJobsDb()
    start_bulk_buy(db, "m1", "b1", [_line("o1")], plan="growth", used_this_month=0)
    rests, turns = [], iter([False, False, True])

    @contextmanager
    def transaction():
        yield db

    d = deps()
    work(
        transaction,
        JobDeps(d.load_order, d.plan_and_usage, d.live_label, sleep=rests.append),
        should_stop=lambda: next(turns),
    )
    assert fake.bought == ["bulk:b1:o1"]
    assert rests == [2.0]
