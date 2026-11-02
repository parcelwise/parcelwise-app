"""Charging for the assistant through the nightly job. The rate, allowance, start month, exemptions, App Store
handling and invoice wording are OPEN in the code; these tests set made-up values (never the real ones) to exercise
the mechanism, and check that nothing is charged while any of them is still open."""

from decimal import Decimal

import pytest

from app.billing import charges, nightly, plans
from app.billing.nightly import assistant_open_calls, charges_for, run
from app.usage.daily import ASSISTANT_ANSWERS
from tests.test_charges import FakeStripe
from tests.test_nightly import FakePostedTable
from tests.test_usage_daily import FakeUsage, rows_for

PLAN_OF = {"m1": "starter", "m2": "growth", "m3": "starter", "m4": "free"}
CUSTOMER_OF = {m: f"cus_{m}" for m in PLAN_OF}
TEST_PRICE = Decimal("0.11")  # test-only; not a proposal for the real rate


@pytest.fixture
def decided(monkeypatch):
    """Stand-in answers for every open call, so the mechanism can run."""
    for name in ("starter", "growth"):
        monkeypatch.setitem(plans.PLANS, name, {**plans.PLANS[name], "assistant_per_month": 100,
                                                "extra_assistant_price": TEST_PRICE})
    monkeypatch.setattr(nightly, "ASSISTANT_COUNTED_FROM", ASSISTANT_ANSWERS)
    monkeypatch.setattr(nightly, "ASSISTANT_BILLING_FROM", "2026-11")
    monkeypatch.setattr(nightly, "ASSISTANT_EXEMPT", frozenset({"m3"}))
    monkeypatch.setattr(nightly, "ASSISTANT_APP_STORE_VIA_STRIPE", False)
    monkeypatch.setitem(charges.FEATURE_LABEL, "assistant", "Assistant answers")


def test_every_open_call_is_still_open_in_the_code():
    assert assistant_open_calls() == [
        "ASSISTANT_COUNTED_FROM", "ASSISTANT_BILLING_FROM", "ASSISTANT_EXEMPT", "ASSISTANT_APP_STORE_VIA_STRIPE", "FEATURE_LABEL['assistant']",
    ]
    for name in ("starter", "growth"):
        assert plans.PLANS[name]["assistant_per_month"] is plans.OPEN
        assert plans.PLANS[name]["extra_assistant_price"] is plans.OPEN


def test_nothing_is_charged_for_the_assistant_while_calls_are_open():
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(rows_for(["m1", "m2"], range(1, 31), feature=ASSISTANT_ANSWERS, count=50))
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, FakePostedTable(), period="2026-11") == 0
    assert FakeStripe.InvoiceItem.created == []


def test_labels_still_bill_while_the_assistant_is_open():
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(rows_for(["m1"], range(1, 31), count=40)
                      + rows_for(["m1"], range(1, 31), feature=ASSISTANT_ANSWERS, count=50))
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, FakePostedTable(), period="2026-06") == 1
    assert FakeStripe.InvoiceItem.created[0]["idempotency_key"] == "m1:labels:2026-06"


def test_charges_answers_past_the_allowance_on_starter_and_growth(decided):
    totals = {("m1", ASSISTANT_ANSWERS): 340, ("m2", ASSISTANT_ANSWERS): 120, ("m4", ASSISTANT_ANSWERS): 0}
    got = [(c.merchant_id, c.feature, c.quantity, c.unit_price) for c in charges_for("2026-11", totals, PLAN_OF)]
    assert got == [("m1", "assistant", 240, TEST_PRICE), ("m2", "assistant", 20, TEST_PRICE)]


def test_within_the_allowance_posts_nothing(decided):
    assert charges_for("2026-11", {("m1", ASSISTANT_ANSWERS): 100}, PLAN_OF) == []


def test_periods_before_the_start_are_never_charged(decided):
    assert charges_for("2026-10", {("m1", ASSISTANT_ANSWERS): 5_000}, PLAN_OF) == []


def test_exempt_merchants_are_not_charged(decided):
    assert charges_for("2026-11", {("m3", ASSISTANT_ANSWERS): 5_000}, PLAN_OF) == []


def test_app_store_merchants_follow_the_app_store_call(decided, monkeypatch):
    totals = {("m1", ASSISTANT_ANSWERS): 200}
    assert charges_for("2026-11", totals, PLAN_OF, {"m1": "app_store"}) == []
    assert len(charges_for("2026-11", totals, PLAN_OF, {"m1": "direct"})) == 1
    monkeypatch.setattr(nightly, "ASSISTANT_APP_STORE_VIA_STRIPE", True)
    assert len(charges_for("2026-11", totals, PLAN_OF, {"m1": "app_store"})) == 1


def test_counting_every_attempt_bills_from_the_attempt_count(decided, monkeypatch):
    monkeypatch.setattr(nightly, "ASSISTANT_COUNTED_FROM", "assistant")
    totals = {("m1", "assistant"): 900, ("m1", ASSISTANT_ANSWERS): 150}
    assert [c.quantity for c in charges_for("2026-11", totals, PLAN_OF)] == [800]


def test_an_unknown_count_is_refused(decided, monkeypatch):
    monkeypatch.setattr(nightly, "ASSISTANT_COUNTED_FROM", "tokens")
    with pytest.raises(ValueError):
        charges_for("2026-11", {}, PLAN_OF)


def test_bills_from_completed_answers_when_that_is_the_count(decided):
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(rows_for(["m1"], [1], feature="assistant", count=900)  # attempts: the model's cost
                      + rows_for(["m1"], [1], feature=ASSISTANT_ANSWERS, count=150))
    usage.rows = [r.__class__(r.day.replace(month=11), r.merchant_id, r.feature, r.count) for r in usage.rows]
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, FakePostedTable(), period="2026-11") == 1
    (created,) = FakeStripe.InvoiceItem.created
    assert created["amount"] == 550  # 50 × $0.11
    assert created["idempotency_key"] == "m1:assistant:2026-11"
    assert created["description"] == "Assistant answers, November 2026: 50 × $0.11"


def test_one_line_per_period_and_rerunning_bills_once(decided):
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage([r.__class__(r.day.replace(month=11), r.merchant_id, r.feature, r.count)
                       for r in rows_for(["m1"], range(1, 31), feature=ASSISTANT_ANSWERS, count=10)])
    posted = FakePostedTable()
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-11") == 1
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-11") == 0
    assert len(FakeStripe.InvoiceItem.created) == 1
