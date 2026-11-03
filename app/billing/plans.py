"""Plans. Prices live in Stripe; this file only holds what the app enforces.

A plan's allowance is what the subscription includes. Past it, a plan with an `extra_label_price` keeps buying
and pays per label on the next invoice (app/billing/nightly.py); a plan without one stops.

The assistant is metered on Starter and Growth (Priya, founders sync Oct 29): `assistant_per_month` answers are
included, and each one past that costs `extra_assistant_price` on the next invoice. The assistant is never
stopped at its allowance. While either value is None, nothing is charged for the assistant on that plan.
"""

from decimal import Decimal

# OPEN: the assistant allowance and price are Priya's to set (Raven task 7fd1f6eb3a29: allowance 3e60d74c0443,
# price 8f9d1b852abf). They stay None until she answers, and None bills nothing.
ASSISTANT_PER_MONTH: dict[str, int | None] = {"starter": None, "growth": None}
EXTRA_ASSISTANT_PRICE: dict[str, Decimal | None] = {"starter": None, "growth": None}

PLANS = {
    "free": {"labels_per_month": 50, "assistant": False, "extra_label_price": None,
             "assistant_per_month": None, "extra_assistant_price": None},
    "starter": {"labels_per_month": 1_000, "assistant": True, "extra_label_price": Decimal("0.08"),
                "assistant_per_month": ASSISTANT_PER_MONTH["starter"],
                "extra_assistant_price": EXTRA_ASSISTANT_PRICE["starter"]},
    "growth": {"labels_per_month": None, "assistant": True, "extra_label_price": None,
               "assistant_per_month": ASSISTANT_PER_MONTH["growth"],
               "extra_assistant_price": EXTRA_ASSISTANT_PRICE["growth"]},
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
