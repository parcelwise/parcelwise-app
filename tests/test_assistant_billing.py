"""Assistant usage billing. The price, allowance, billable count, first month and install sources are open calls
(Raven task 7fd1f6eb3a29); the numbers below are test inputs only, not the product's values."""

from decimal import Decimal

import pytest

from app.billing import nightly
from app.billing.charges import Charge
from app.billing.nightly import METERED, charges_for, metered, run
from app.billing.plans import PLANS
from tests.test_charges import FakeStripe
from tests.test_nightly import CUSTOMER_OF, PLAN_OF, FakePostedTable
from tests.test_usage_daily import FakeUsage, rows_for

TEST_PRICE = Decimal("0.05")
EVERYONE = frozenset({"direct", "app_store"})
DIRECT = {"m1": "direct", "m2": "direct", "m3": "direct"}


@pytest.fixture
def priced(monkeypatch):
    """Give Starter and Growth a test allowance and price for the assistant."""
    for plan, allowance in (("starter", 100), ("growth", 300)):
        monkeypatch.setitem(PLANS, plan, {**PLANS[plan], "assistant_per_month": allowance,
                                          "extra_assistant_price": TEST_PRICE})


def meters(**overrides):
    args = {"assistant_usage_feature": "assistant", "assistant_first_period": "2026-11",
            "assistant_install_sources": EVERYONE}
    return metered(**{**args, **overrides})


def test_assistant_is_not_metered_until_every_open_input_is_set():
    assert "assistant" not in METERED
    assert nightly.ASSISTANT_USAGE_FEATURE is None
    assert nightly.ASSISTANT_FIRST_PERIOD is None
    assert nightly.ASSISTANT_INSTALL_SOURCES is None
    for missing in ("assistant_usage_feature", "assistant_first_period", "assistant_install_sources"):
        assert "assistant" not in meters(**{missing: None})
    assert "assistant" in meters()


def test_unpriced_plans_charge_nothing_for_the_assistant():
    totals = {("m1", "assistant"): 50_000, ("m3", "assistant"): 50_000}
    assert charges_for("2026-11", totals, PLAN_OF, meters=meters(), install_source_of=DIRECT) == []


def test_a_merchant_with_no_known_install_source_is_not_charged_for_the_assistant(priced):
    assert charges_for("2026-11", {("m1", "assistant"): 500}, PLAN_OF, meters=meters()) == []


def test_answers_past_the_allowance_are_charged_per_plan(priced):
    totals = {("m1", "assistant"): 160, ("m2", "assistant"): 999, ("m3", "assistant"): 450}
    charges = charges_for("2026-11", totals, PLAN_OF, meters=meters(), install_source_of=DIRECT)
    assert charges == [Charge("m1", "assistant", "2026-11", 60, TEST_PRICE),
                       Charge("m3", "assistant", "2026-11", 150, TEST_PRICE)]  # m2 is Free: never charged


def test_within_the_allowance_charges_nothing(priced):
    assert charges_for("2026-11", {("m1", "assistant"): 100}, PLAN_OF, meters=meters(),
                       install_source_of=DIRECT) == []


def test_months_before_the_first_billed_month_are_never_charged(priced):
    totals = {("m1", "assistant"): 500, ("m1", "labels"): 1_100}
    charges = charges_for("2026-10", totals, PLAN_OF, meters=meters(assistant_first_period="2026-11"),
                          install_source_of=DIRECT)
    assert [(c.feature, c.quantity) for c in charges] == [("labels", 100)]


def test_billed_quantity_reads_the_usage_feature_it_is_given(priced):
    totals = {("m1", "assistant"): 500, ("m1", "assistant_answers"): 120}
    charges = charges_for("2026-11", totals, PLAN_OF, meters=meters(assistant_usage_feature="assistant_answers"),
                          install_source_of=DIRECT)
    assert [(c.feature, c.quantity) for c in charges] == [("assistant", 20)]
    assert charges[0].idempotency_key == "m1:assistant:2026-11"


def test_install_sources_limit_who_is_charged(priced):
    totals = {("m1", "assistant"): 200, ("m4", "assistant"): 200}
    plan_of = {**PLAN_OF, "m4": "starter"}
    sources = {"m1": "direct", "m4": "app_store"}
    only_direct = meters(assistant_install_sources=frozenset({"direct"}))
    charges = charges_for("2026-11", totals, plan_of, meters=only_direct, install_source_of=sources)
    assert [c.merchant_id for c in charges] == ["m1"]
    assert len(charges_for("2026-11", totals, plan_of, meters=meters(), install_source_of=sources)) == 2


def test_labels_are_charged_whatever_the_install_source():
    charges = charges_for("2026-06", {("m1", "labels"): 1_212}, PLAN_OF, meters=meters(),
                          install_source_of={"m1": "app_store"})
    assert [(c.feature, c.quantity) for c in charges] == [("labels", 212)]


def test_run_posts_one_assistant_line_per_merchant_and_month_and_bills_once(priced):
    FakeStripe.InvoiceItem.created.clear()
    rows = rows_for(["m1"], range(1, 31), feature="assistant", count=4)  # 120 answers
    rows = [r.__class__(r.day.replace(month=11), r.merchant_id, r.feature, r.count) for r in rows]
    usage, posted = FakeUsage(rows), FakePostedTable()
    sources = {"m1": "direct"}
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-11", meters=meters(),
               install_source_of=sources) == 1
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-11", meters=meters(),
               install_source_of=sources) == 0
    (created,) = FakeStripe.InvoiceItem.created
    assert created["amount"] == 100 and created["idempotency_key"] == "m1:assistant:2026-11"
    assert created["description"] == "Assistant answers, November 2026: 20 × $0.05"
