from datetime import date
from decimal import Decimal

import pytest

from app.billing import nightly
from app.billing.nightly import METERED, Metered, charges_for, closed_period, run
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


# Assistant answers. The rates and allowances here are test values, not prices: the real ones are open.
TEST_ASSISTANT = {"assistant_answers_per_month": 100, "assistant_answer_price": Decimal("0.10")}


def assistant_rule(**overrides):
    fields = {"starts": "2026-06", "exempt_shops": frozenset({"exempt.myshopify.com"}), "bill_app_store": False}
    fields.update(overrides)
    return {"labels": METERED["labels"], "assistant": Metered("assistant_answers_per_month",
                                                              "assistant_answer_price", **fields)}


@pytest.fixture
def priced(monkeypatch):
    for name in ("starter", "growth"):
        monkeypatch.setitem(nightly.PLANS, name, {**nightly.PLANS[name], **TEST_ASSISTANT})


SHOP_OF = {"m1": "one.myshopify.com", "m3": "three.myshopify.com", "mx": "exempt.myshopify.com"}
SOURCE_OF = {"m1": "direct", "m3": "direct", "mx": "direct"}
PLANS_OF = {**PLAN_OF, "mx": "growth"}


def assistant_charges(totals, period="2026-06", **kwargs):
    kwargs.setdefault("shop_of", SHOP_OF)
    kwargs.setdefault("source_of", SOURCE_OF)
    kwargs.setdefault("metered", assistant_rule())
    return [(c.merchant_id, c.feature, c.quantity, c.unit_price)
            for c in charges_for(period, totals, PLANS_OF, **kwargs)]


def test_assistant_charges_nothing_while_its_open_inputs_are_unset(priced):
    assert not METERED["assistant"].ready()
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(rows_for(["m1"], range(1, 31), feature="assistant", count=50))
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, FakePostedTable(), period="2026-06",
               shop_of=SHOP_OF, source_of=SOURCE_OF) == 0
    assert usage.reads == 1  # one page of labels; the assistant is not even read
    assert FakeStripe.InvoiceItem.created == []


def test_assistant_unpriced_plans_charge_nothing():
    assert assistant_charges({("m1", "assistant"): 5_000}) == []


def test_starter_and_growth_pay_past_the_allowance(priced):
    totals = {("m1", "assistant"): 130, ("m3", "assistant"): 101, ("m2", "assistant"): 500}
    assert assistant_charges(totals) == [
        ("m1", "assistant", 30, Decimal("0.10")),
        ("m3", "assistant", 1, Decimal("0.10")),
    ]


def test_no_assistant_charge_before_the_start_month(priced):
    assert assistant_charges({("m1", "assistant"): 500}, period="2026-05") == []


def test_exempt_shops_and_unknown_shops_are_not_charged(priced):
    totals = {("mx", "assistant"): 500, ("m3", "assistant"): 500}
    assert assistant_charges(totals, shop_of={"mx": "exempt.myshopify.com"}) == []


def test_app_store_installs_and_unknown_sources_are_skipped_when_not_billed_through_stripe(priced):
    totals = {("m1", "assistant"): 500, ("m3", "assistant"): 500}
    assert assistant_charges(totals, source_of={"m1": "app_store"}) == []
    assert assistant_charges(totals, source_of={"m1": "app_store", "m3": "app_store"},
                             metered=assistant_rule(bill_app_store=True)) == [
        ("m1", "assistant", 400, Decimal("0.10")),
        ("m3", "assistant", 400, Decimal("0.10")),
    ]


def test_assistant_charges_post_through_the_nightly_job_once(priced):
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(rows_for(["m1"], range(1, 31), feature="assistant", count=5))  # 150 answers
    posted = FakePostedTable()
    for _ in range(2):
        run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-06",
            shop_of=SHOP_OF, source_of=SOURCE_OF, metered=assistant_rule())
    (created,) = FakeStripe.InvoiceItem.created
    assert created["amount"] == 500 and created["idempotency_key"] == "m1:assistant:2026-06"


def test_labels_are_charged_as_before_whatever_the_assistant_inputs():
    totals = {("m1", "labels"): 1_212}
    assert charges_for("2026-06", totals, PLAN_OF) == charges_for("2026-06", totals, PLAN_OF, metered=assistant_rule())
