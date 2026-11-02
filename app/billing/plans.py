"""Plans. Prices live in Stripe; this file only holds what the app enforces.

A plan's allowance is what the subscription includes. Past it, a plan with an `extra_label_price` keeps buying
and pays per label on the next invoice (app/billing/nightly.py); a plan without one stops.

The assistant is metered on Starter and Growth, in arrears on the monthly invoice like extra labels (Priya,
founders sync Oct 29). Free has no assistant, so nothing is metered there. Past the included answers each one
costs $0.04 (Priya). The included answers are still Priya's to set: they stay `Open` until she does, and nothing
charges for the assistant while they are.
"""

from decimal import Decimal

from app.billing.open_calls import Open

ASSISTANT_ALLOWANCE = Open("3e7cfb720dab", "How many assistant answers a month are included, per plan?")
ASSISTANT_PRICE = Decimal("0.04")  # per answer past the allowance, Starter and Growth (Priya, Raven ea7114b15829)

PLANS = {
    "free": {
        "labels_per_month": 50, "assistant": False, "extra_label_price": None,
        "assistant_answers_per_month": None, "assistant_answer_price": None,
    },
    "starter": {
        "labels_per_month": 1_000, "assistant": True, "extra_label_price": Decimal("0.08"),
        "assistant_answers_per_month": ASSISTANT_ALLOWANCE, "assistant_answer_price": ASSISTANT_PRICE,
    },
    "growth": {
        "labels_per_month": None, "assistant": True, "extra_label_price": None,
        "assistant_answers_per_month": ASSISTANT_ALLOWANCE, "assistant_answer_price": ASSISTANT_PRICE,
    },
}


def monthly_allowance(plan: str) -> int | None:
    """None means unlimited."""
    return PLANS[plan]["labels_per_month"]


def within_allowance(plan: str, used_this_month: int) -> bool:
    allowance = monthly_allowance(plan)
    return allowance is None or used_this_month < allowance


def can_buy_label(plan: str, used_this_month: int) -> bool:
    """Within the allowance, or on a plan that charges for extra labels."""
    return within_allowance(plan, used_this_month) or PLANS[plan]["extra_label_price"] is not None


def has_assistant(plan: str) -> bool:
    """The assistant is part of the paid plans; Free does not get it (Priya, #55)."""
    return PLANS[plan]["assistant"]
