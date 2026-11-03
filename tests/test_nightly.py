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


def assistant_rows(merchant, days, count, month=12, year=2026):
    from app.usage.daily import DailyCount

    return [DailyCount(date(year, month, d), merchant, "assistant_answers", count) for d in days]


def test_assistant_is_never_billed_before_december_2026():
    from app.billing.nightly import billed_features

    assert billed_features("2026-11") == {"labels"}
    assert billed_features("2026-12") == {"labels", "assistant_answers"}
    assert charges_for("2026-11", {("m1", "assistant_answers"): 5_000}, PLAN_OF) == []


def test_assistant_reads_nothing_before_it_bills():
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(assistant_rows("m1", range(1, 31), 50, month=11))
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, FakePostedTable(), period="2026-11") == 0
    assert FakeStripe.InvoiceItem.created == []


def test_open_assistant_values_hold_back_assistant_charges_but_labels_still_post(monkeypatch):
    import pytest

    from app.billing import plans
    from app.billing.nightly import OpenDecision

    monkeypatch.setattr(plans, "OFF_PUBLIC_ASSISTANT_RATE", frozenset())
    monkeypatch.setitem(plans.PLANS["starter"], "assistant_price", plans.Open("test: price not decided"))
    FakeStripe.InvoiceItem.created.clear()
    from app.usage.daily import DailyCount

    labels = [DailyCount(date(2026, 12, d), "m1", "labels", 40) for d in range(1, 31)]
    usage = FakeUsage(labels + assistant_rows("m1", range(1, 31), 10))
    with pytest.raises(OpenDecision, match="1 charges posted for 2026-12; held back: starter.assistant_price is not decided: test"):
        run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, FakePostedTable(), period="2026-12")
    assert [c["description"] for c in FakeStripe.InvoiceItem.created] == ["Extra labels, December 2026: 200 × $0.08"]


def test_assistant_charges_one_line_per_period_past_the_allowance(monkeypatch):
    from app.billing import plans

    monkeypatch.setattr(plans, "OFF_PUBLIC_ASSISTANT_RATE", frozenset())
    for name in ("starter", "growth"):
        monkeypatch.setitem(plans.PLANS[name], "assistant_per_month", 100)  # test values, not the real ones
        monkeypatch.setitem(plans.PLANS[name], "assistant_price", Decimal("0.05"))
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(assistant_rows("m1", range(1, 31), 10) + assistant_rows("m3", range(1, 3), 10))
    posted = FakePostedTable()
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-12") == 1
    (created,) = FakeStripe.InvoiceItem.created
    assert created["customer"] == "cus_1" and created["amount"] == 1000
    assert created["description"] == "Assistant answers, December 2026: 200 × $0.05"
    assert created["idempotency_key"] == "m1:assistant_answers:2026-12"
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-12") == 0


def test_attempts_are_never_billed_only_completed_answers(monkeypatch):
    from app.billing import plans

    monkeypatch.setattr(plans, "OFF_PUBLIC_ASSISTANT_RATE", frozenset())
    monkeypatch.setitem(plans.PLANS["starter"], "assistant_per_month", 0)  # test values, not the real ones
    monkeypatch.setitem(plans.PLANS["starter"], "assistant_price", Decimal("0.05"))
    totals = {("m1", "assistant"): 900, ("m1", "assistant_answers"): 300}
    (charge,) = charges_for("2026-12", totals, PLAN_OF)
    assert (charge.feature, charge.quantity) == ("assistant_answers", 300)


def test_app_store_installs_get_no_assistant_charge_but_keep_label_charges(monkeypatch):
    from app.billing import plans

    monkeypatch.setattr(plans, "OFF_PUBLIC_ASSISTANT_RATE", frozenset())
    monkeypatch.setitem(plans.PLANS["starter"], "assistant_per_month", 0)  # test values, not the real ones
    monkeypatch.setitem(plans.PLANS["starter"], "assistant_price", Decimal("0.05"))
    totals = {("m1", "assistant_answers"): 300, ("m1", "labels"): 1_100}
    charges = charges_for("2026-12", totals, PLAN_OF, {"m1": "app_store"})
    assert [(c.feature, c.quantity) for c in charges] == [("labels", 100)]
    direct = charges_for("2026-12", totals, PLAN_OF, {"m1": "direct"})
    assert [c.feature for c in direct] == ["assistant_answers", "labels"]


def test_starter_and_growth_include_500_assistant_answers():
    from app.billing.plans import PLANS

    assert PLANS["starter"]["assistant_per_month"] == PLANS["growth"]["assistant_per_month"] == 500
    assert PLANS["free"]["assistant_per_month"] is None


def test_the_public_assistant_rate_is_two_cents_past_500(monkeypatch):
    from app.billing import plans

    monkeypatch.setattr(plans, "OFF_PUBLIC_ASSISTANT_RATE", frozenset())
    (charge,) = charges_for("2026-12", {("m1", "assistant_answers"): 650}, PLAN_OF)
    assert plans.PLANS["starter"]["assistant_price"] == Decimal("0.02")
    assert (charge.quantity, charge.amount) == (150, Decimal("3.00"))
    assert charge.description == "Assistant answers, December 2026: 150 × $0.02"


def test_bloom_and_co_pays_nothing_for_the_assistant():
    from app.billing import plans

    assert "bloom-and-co.myshopify.com" in plans.OFF_PUBLIC_ASSISTANT_RATE
    totals = {("m3", "assistant_answers"): 5_000, ("m1", "assistant_answers"): 650}
    shop_of = {"m3": "bloom-and-co.myshopify.com", "m1": "other.myshopify.com"}
    assert [(c.merchant_id, c.quantity) for c in charges_for("2026-12", totals, PLAN_OF, shop_of=shop_of)] == [
        ("m1", 150)
    ]


def test_an_open_shop_list_holds_back_assistant_charges(monkeypatch):
    import pytest

    from app.billing import plans
    from app.billing.nightly import OpenDecision

    monkeypatch.setattr(plans, "OFF_PUBLIC_ASSISTANT_RATE", plans.Open("test: shops not named"))
    with pytest.raises(OpenDecision, match="shops not named"):
        charges_for("2026-12", {("m1", "assistant_answers"): 650}, PLAN_OF)
    assert [c.feature for c in charges_for("2026-12", {("m1", "labels"): 1_100}, PLAN_OF)] == ["labels"]


def test_merchants_off_the_public_rate_get_no_assistant_charge(monkeypatch):
    from app.billing import plans

    monkeypatch.setattr(plans, "OFF_PUBLIC_ASSISTANT_RATE", frozenset({"shop-1.myshopify.com"}))
    totals = {("m1", "assistant_answers"): 650, ("m3", "assistant_answers"): 650, ("m1", "labels"): 1_100}
    shop_of = {"m1": "shop-1.myshopify.com", "m3": "shop-3.myshopify.com"}
    assert [(c.merchant_id, c.feature) for c in charges_for("2026-12", totals, PLAN_OF, shop_of=shop_of)] == [
        ("m1", "labels"),
        ("m3", "assistant_answers"),
    ]
