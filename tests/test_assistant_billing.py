"""Assistant charges: the mechanism, with the open values (rate, allowance, start month, Bloom & Co's id, App
Store handling, invoice wording) filled in by each test. The real values are owners' calls (see nightly.GATES)."""

from decimal import Decimal

import pytest

from app.billing import charges, nightly, plans
from app.billing.nightly import billable_features, charges_for, gate_ready, run
from app.shopify.install import APP_STORE, DIRECT
from tests.test_charges import FakeStripe
from tests.test_nightly import FakePostedTable
from tests.test_usage_daily import FakeUsage, rows_for

PLAN_OF = {"m1": "starter", "m2": "growth", "bloom": "growth", "shop": "starter"}
CUSTOMER_OF = {m: f"cus_{m}" for m in PLAN_OF}


def test_assistant_posts_nothing_until_its_owners_fill_in_the_inputs():
    """As shipped: no rate, no allowance, no start month. Today's behaviour (we eat the cost) holds."""
    assert not gate_ready("assistant")
    assert billable_features() == ["labels"]
    totals = {("m1", "assistant"): 5_000, ("m2", "assistant"): 5_000}
    assert charges_for("2026-11", totals, PLAN_OF) == []
    for plan in plans.PLANS.values():
        assert plan["assistant_answers_per_month"] is None and plan["extra_assistant_price"] is None


@pytest.fixture
def filled_in(monkeypatch):
    """Test values only. None of these numbers, dates or ids is a decision."""
    monkeypatch.setitem(nightly.GATES, "assistant",
                        {"billed_from": "2026-12", "exempt": frozenset({"bloom"}), "app_store": "skip"})
    monkeypatch.setitem(charges.FEATURE_LABEL, "assistant", "Assistant answers")
    for name in ("starter", "growth"):
        monkeypatch.setitem(plans.PLANS, name, {**plans.PLANS[name], "assistant_answers_per_month": 100,
                                                "extra_assistant_price": Decimal("0.05")})


@pytest.mark.parametrize("key", ["billed_from", "exempt", "app_store"])
def test_each_gate_input_on_its_own_holds_the_feature_back(filled_in, monkeypatch, key):
    assert gate_ready("assistant")
    monkeypatch.setitem(nightly.GATES["assistant"], key, None)
    assert not gate_ready("assistant")
    assert charges_for("2026-12", {("m1", "assistant"): 5_000}, PLAN_OF) == []


def test_invoice_wording_is_a_gate_input(filled_in, monkeypatch):
    monkeypatch.delitem(charges.FEATURE_LABEL, "assistant")
    assert not gate_ready("assistant")


def test_answers_past_the_allowance_are_charged_on_starter_and_growth(filled_in):
    totals = {("m1", "assistant"): 340, ("m2", "assistant"): 100}
    (charge,) = charges_for("2026-12", totals, PLAN_OF)
    assert (charge.merchant_id, charge.feature, charge.quantity, charge.unit_price) == (
        "m1", "assistant", 240, Decimal("0.05"))
    assert charge.amount == Decimal("12.00")
    assert charge.description == "Assistant answers, December 2026: 240 × $0.05"
    assert charge.idempotency_key == "m1:assistant:2026-12"


def test_periods_before_the_start_month_are_never_charged(filled_in):
    assert charges_for("2026-11", {("m1", "assistant"): 5_000}, PLAN_OF) == []


def test_exempt_merchants_are_not_charged(filled_in):
    assert charges_for("2026-12", {("bloom", "assistant"): 5_000}, PLAN_OF) == []


def test_app_store_installs_follow_the_app_store_input(filled_in, monkeypatch):
    totals = {("shop", "assistant"): 500}
    assert charges_for("2026-12", totals, PLAN_OF, {"shop": APP_STORE}) == []
    assert len(charges_for("2026-12", totals, PLAN_OF, {"shop": DIRECT})) == 1
    monkeypatch.setitem(nightly.GATES["assistant"], "app_store", "bill")
    assert len(charges_for("2026-12", totals, PLAN_OF, {"shop": APP_STORE})) == 1


def test_gates_never_touch_extra_labels(filled_in):
    totals = {("shop", "labels"): 1_100}
    (charge,) = charges_for("2026-11", totals, PLAN_OF, {"shop": APP_STORE})
    assert (charge.feature, charge.quantity) == ("labels", 100)


def test_run_posts_one_line_per_feature_and_rerunning_posts_nothing(filled_in):
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(
        [r.__class__(r.day.replace(month=12), r.merchant_id, r.feature, r.count)
         for r in rows_for(["m1"], range(1, 31), feature="assistant", count=10)
         + rows_for(["m1"], range(1, 31), feature="labels", count=40)]
    )
    posted = FakePostedTable()
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-12") == 2
    assert sorted(c["description"] for c in FakeStripe.InvoiceItem.created) == [
        "Assistant answers, December 2026: 200 × $0.05",
        "Extra labels, December 2026: 200 × $0.08",
    ]
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-12") == 0
    assert len(FakeStripe.InvoiceItem.created) == 2
