"""Assistant charges through the nightly job, with the values decided in Raven task afdabadc60bd. One input is
still open (the exempt merchant's id); the tests check that the shipped config posts nothing while it is, and fill
it with a stand-in to test the mechanism."""

from dataclasses import replace
from decimal import Decimal

import pytest

from app.billing import plans
from app.billing.charges import Charge
from app.billing.nightly import BLOOM_AND_CO, METERED, SKIP, charges_for, ready, run, waiting
from app.usage.daily import ASSISTANT_ANSWERS
from tests.test_charges import FakeStripe
from tests.test_nightly import FakePostedTable
from tests.test_usage_daily import FakeUsage, rows_for

PLAN_OF = {"m1": "starter", "m2": "growth", "m3": "free", "bloom": "growth", "shop": "starter"}
CUSTOMER_OF = {m: f"cus_{m}" for m in PLAN_OF}
PRICE = Decimal("0.04")  # Priya's rate


@pytest.fixture
def decided():
    """The assistant with its one open input (Bloom & Co's merchant id) filled in by a stand-in,
    and an earlier start so June test data bills."""
    assistant = replace(METERED["assistant"], starts="2026-06", exempt={"bloom": "2026-07", "forever": None})
    return {"labels": METERED["labels"], "assistant": assistant}


def test_shipped_config_bills_no_assistant_while_inputs_are_open():
    assert "assistant" not in ready() and "labels" in ready()
    assert waiting()["assistant"] == [BLOOM_AND_CO]


def test_bloom_and_co_free_through_january_2027():
    assert METERED["assistant"].exempt == {BLOOM_AND_CO: "2027-01"}


def test_shopify_usage_cap_is_fifty_dollars():
    assert plans.SHOPIFY_ASSISTANT_USAGE_CAP == Decimal("50.00")


def test_first_billed_month_is_december_and_app_store_installs_never_go_through_stripe():
    assert METERED["assistant"].starts == "2026-12"
    assert METERED["assistant"].app_store == SKIP


def test_starter_includes_200_answers_and_growth_1000():
    assert plans.PLANS["starter"]["assistant_answers_per_month"] == 200
    assert plans.PLANS["growth"]["assistant_answers_per_month"] == 1_000


def test_starter_and_growth_pay_four_cents_an_answer():
    assert plans.PLANS["starter"]["extra_assistant_answer_price"] == PRICE
    assert plans.PLANS["growth"]["extra_assistant_answer_price"] == PRICE
    assert plans.PLANS["free"]["extra_assistant_answer_price"] is None


def test_assistant_bills_completed_answers_not_attempts():
    assert METERED["assistant"].usage_feature == ASSISTANT_ANSWERS


def test_shipped_config_posts_only_labels():
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(rows_for(["m1"], range(1, 31), feature=ASSISTANT_ANSWERS, count=50)
                      + rows_for(["m1"], range(1, 31), count=40))
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, FakePostedTable(), period="2026-06") == 1
    (created,) = FakeStripe.InvoiceItem.created
    assert created["idempotency_key"] == "m1:labels:2026-06"


def test_starter_and_growth_pay_past_the_allowance_and_free_never(decided):
    totals = {("m1", ASSISTANT_ANSWERS): 340, ("m2", ASSISTANT_ANSWERS): 1_000, ("m3", ASSISTANT_ANSWERS): 500}
    charges = charges_for("2026-06", totals, PLAN_OF, metered=decided)
    assert charges == [Charge("m1", "assistant", "2026-06", 140, PRICE)]


def test_growth_pays_too(decided):
    charges = charges_for("2026-06", {("m2", ASSISTANT_ANSWERS): 1_001}, PLAN_OF, metered=decided)
    assert [(c.merchant_id, c.quantity) for c in charges] == [("m2", 1)]


def test_nothing_before_the_start_month(decided):
    assert charges_for("2026-05", {("m1", ASSISTANT_ANSWERS): 340}, PLAN_OF, metered=decided) == []


def test_exemptions_hold_through_their_last_month(decided):
    plan_of = dict(PLAN_OF, forever="growth")
    totals = {("bloom", ASSISTANT_ANSWERS): 5_000, ("forever", ASSISTANT_ANSWERS): 5_000}
    assert charges_for("2026-06", totals, plan_of, metered=decided) == []
    assert charges_for("2026-07", totals, plan_of, metered=decided) == []
    assert [c.merchant_id for c in charges_for("2026-08", totals, plan_of, metered=decided)] == ["bloom"]


def test_app_store_installs_are_skipped(decided):
    totals = {("shop", ASSISTANT_ANSWERS): 500}
    assert charges_for("2026-06", totals, PLAN_OF, install_of={"shop": "app_store"}, metered=decided) == []
    assert len(charges_for("2026-06", totals, PLAN_OF, install_of={"shop": "direct"}, metered=decided)) == 1


def test_attempts_are_never_billed(decided):
    totals = {("m1", "assistant"): 900, ("m1", ASSISTANT_ANSWERS): 250}
    (charge,) = charges_for("2026-06", totals, PLAN_OF, metered=decided)
    assert charge.feature == "assistant" and charge.quantity == 50


def test_one_invoice_line_per_period_and_its_own_key(decided):
    FakeStripe.InvoiceItem.created.clear()
    usage = FakeUsage(rows_for(["m1"], range(1, 31), feature=ASSISTANT_ANSWERS, count=10)
                      + rows_for(["m1"], range(1, 31), count=40))
    posted = FakePostedTable()
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-06", metered=decided) == 2
    assistant = [c for c in FakeStripe.InvoiceItem.created if c["idempotency_key"] == "m1:assistant:2026-06"]
    assert len(assistant) == 1
    assert assistant[0]["description"] == "Assistant answers, June 2026: 100 × $0.04"
    assert assistant[0]["amount"] == 400
    assert run(usage, PLAN_OF, CUSTOMER_OF, FakeStripe, posted, period="2026-06", metered=decided) == 0
