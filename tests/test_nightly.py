from datetime import date
from decimal import Decimal

from app.billing.nightly import charges_for, closed_period, run
from tests.test_charges import FakePosted, FakeStripe
from tests.test_usage_daily import FakeUsage, rows_for

PLAN_OF = {"m1": "starter", "m2": "free", "m3": "growth"}
CUSTOMER_OF = {"m1": "cus_1", "m2": "cus_2", "m3": "cus_3"}


class FakePostedTable(FakePosted):
    def __init__(self):
        super().__init__()
        self.transactions = 0

    def transaction(self):
        from contextlib import nullcontext

        self.transactions += 1
        return nullcontext()


def test_only_starter_pays_past_its_allowance():
    totals = {("m1", "labels"): 1_212, ("m2", "labels"): 50, ("m3", "labels"): 9_000}
    charges = charges_for("2026-06", totals, PLAN_OF)
    assert [(c.merchant_id, c.quantity, c.unit_price) for c in charges] == [("m1", 212, Decimal("0.08"))]


def test_within_the_allowance_posts_nothing():
    assert charges_for("2026-06", {("m1", "labels"): 1_000}, PLAN_OF) == []


def test_closed_period_is_last_month():
    assert closed_period(date(2026, 7, 1)) == "2026-06"
    assert closed_period(date(2026, 1, 3)) == "2025-12"


def test_run_reads_the_daily_counts_and_posts_one_charge_per_merchant():
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(rows_for(["m1"], range(1, 31), count=40))  # 1,200 labels in June
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, FakePostedTable(), period="2026-06") == 1
    (created,) = FakeStripe.InvoiceItem.created
    assert created["customer"] == "cus_1" and created["amount"] == 1600


def test_rerunning_the_job_posts_nothing_twice():
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(rows_for(["m1"], range(1, 31), count=40))
    posted = FakePostedTable()
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-06") == 1
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-06") == 0
    assert len(FakeStripe.InvoiceItem.created) == 1


def test_charges_post_in_batches_of_one_hundred():
    from app.billing.nightly import BATCH

    FakeStripe.InvoiceItem.created.clear()
    merchants = [f"s{i:03d}" for i in range(250)]
    usage = FakeUsage(rows_for(merchants, [1], count=1_001))
    posted = FakePostedTable()
    plan_of = {m: "starter" for m in merchants}
    customer_of = {m: f"cus_{m}" for m in merchants}
    assert BATCH == 100
    assert run(usage, plan_of, customer_of, FakeStripe, posted, period="2026-06") == 250
    assert posted.transactions == 3
