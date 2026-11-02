"""Charging for the assistant. It bills completed answers, not attempts (Jordan). Its price, allowance, start month,
exemptions and App Store handling are open in Raven; until they are answered, nothing charges for it and label charges carry on as before."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.billing import nightly
from app.billing.charges import Charge
from app.billing.nightly import METERED, Held, charges_for, run
from app.billing.open_calls import is_open
from app.billing.plans import PLANS
from app.usage.daily import ASSISTANT_ANSWERED
from tests.test_charges import FakeStripe
from tests.test_nightly import FakePostedTable
from tests.test_usage_daily import FakeUsage, rows_for

PLAN_OF = {"m1": "starter", "m2": "growth", "m3": "free"}
CUSTOMER_OF = {"m1": "cus_1", "m2": "cus_2", "m3": "cus_3"}


@pytest.fixture
def answered(monkeypatch):
    """Example answers so the mechanism can be exercised. These numbers are test inputs, not decisions."""

    def fill(*, allowance=100, price=Decimal("0.02"), first_period="2026-06", exempt=frozenset(),
             charge_app_store=True, counted_from=ASSISTANT_ANSWERED):
        plans = {name: dict(plan) for name, plan in PLANS.items()}
        for name in ("starter", "growth"):
            plans[name]["assistant_answers_per_month"] = allowance
            plans[name]["assistant_answer_price"] = price
        monkeypatch.setattr(nightly, "PLANS", plans)
        metered = dict(METERED)
        metered["assistant"] = replace(METERED["assistant"], counted_from=counted_from, first_period=first_period,
                                       exempt=frozenset(exempt), charge_app_store=charge_app_store)
        monkeypatch.setattr(nightly, "METERED", metered)

    return fill


def test_the_open_calls_are_still_open():
    assistant = METERED["assistant"]
    for value in (assistant.first_period, assistant.exempt, assistant.charge_app_store,
                  PLANS["starter"]["assistant_answers_per_month"], PLANS["growth"]["assistant_answers_per_month"]):
        assert is_open(value)


def test_starter_and_growth_pay_four_cents_an_answer_past_the_allowance():
    assert PLANS["starter"]["assistant_answer_price"] == PLANS["growth"]["assistant_answer_price"] == Decimal("0.04")


def test_free_has_no_assistant_to_meter():
    assert PLANS["free"]["assistant_answers_per_month"] is None and PLANS["free"]["assistant_answer_price"] is None


def test_until_answered_nothing_charges_for_the_assistant_and_labels_still_do():
    held = Held()
    totals = {("m1", "assistant"): 5_000, ("m2", "assistant"): 5_000, ("m1", "labels"): 1_212}
    charges = charges_for("2026-06", totals, PLAN_OF, held=held)
    assert [(c.feature, c.quantity) for c in charges] == [("labels", 212)]
    assert len(held) == 2
    assert held.by_node == {"22fc5b84721e": {("m1", "assistant"), ("m2", "assistant")}}


def test_the_nightly_run_posts_labels_and_holds_the_assistant():
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(rows_for(["m1"], range(1, 31), count=40) + rows_for(["m1"], [3], feature=ASSISTANT_ANSWERED, count=9))
    held = Held()
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, FakePostedTable(), period="2026-06", held=held) == 1
    assert [c["description"] for c in FakeStripe.InvoiceItem.created] == ["Extra labels, June 2026: 200 × $0.08"]
    assert len(held) == 1


def test_once_answered_starter_and_growth_pay_past_the_allowance(answered):
    answered()
    totals = {("m1", "assistant"): 130, ("m2", "assistant"): 100, ("m3", "assistant"): 500}
    assert charges_for("2026-06", totals, PLAN_OF) == [Charge("m1", "assistant", "2026-06", 30, Decimal("0.02"))]


def test_the_assistant_line_reads_like_the_labels_line():
    charge = Charge("m1", "assistant", "2026-06", 30, Decimal("0.02"))
    assert charge.description == "Assistant answers, June 2026: 30 × $0.02"
    assert charge.amount == Decimal("0.60") and charge.idempotency_key == "m1:assistant:2026-06"


def test_months_before_the_first_charged_month_post_nothing(answered):
    answered(first_period="2026-07")
    assert charges_for("2026-06", {("m1", "assistant"): 500}, PLAN_OF) == []
    assert len(charges_for("2026-07", {("m1", "assistant"): 500}, PLAN_OF)) == 1


def test_exempt_merchants_are_not_charged(answered):
    answered(exempt={"m2"})
    charges = charges_for("2026-06", {("m1", "assistant"): 500, ("m2", "assistant"): 500}, PLAN_OF)
    assert [c.merchant_id for c in charges] == ["m1"]


def test_app_store_merchants_wait_on_their_own_call(answered, monkeypatch):
    answered()
    metered = dict(nightly.METERED)
    metered["assistant"] = replace(metered["assistant"], charge_app_store=METERED["assistant"].charge_app_store)
    monkeypatch.setattr(nightly, "METERED", metered)
    held = Held()
    charges = charges_for("2026-06", {("m1", "assistant"): 500, ("m2", "assistant"): 500}, PLAN_OF,
                          source_of={"m2": "app_store"}, held=held)
    assert [c.merchant_id for c in charges] == ["m1"]
    assert held.by_node == {"b9d5a20eb56f": {("m2", "assistant")}}


def test_app_store_merchants_skipped_when_that_is_the_answer(answered):
    answered(charge_app_store=False)
    charges = charges_for("2026-06", {("m2", "assistant"): 500}, PLAN_OF, source_of={"m2": "app_store"})
    assert charges == []


def test_billing_reads_completed_answers_not_attempts():
    assert METERED["assistant"].counted_from == ASSISTANT_ANSWERED
    usage = FakeUsage(rows_for(["m1"], [1], feature="assistant", count=500)
                      + rows_for(["m1"], [1], feature=ASSISTANT_ANSWERED, count=120))
    assert nightly.billable_totals(usage, "2026-06")[("m1", "assistant")] == 120


def test_rerunning_posts_the_assistant_charge_once(answered):
    answered()
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(rows_for(["m1"], range(1, 11), feature=ASSISTANT_ANSWERED, count=20))  # 200 answers
    posted = FakePostedTable()
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-06") == 1
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-06") == 0
    (created,) = FakeStripe.InvoiceItem.created
    assert created["amount"] == 200 and created["idempotency_key"] == "m1:assistant:2026-06"
