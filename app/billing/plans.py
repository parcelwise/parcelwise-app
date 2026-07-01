"""Plans. Prices live in Stripe; this file only holds what the app enforces.

A plan's allowance is what the subscription includes. Past it, a plan with an `extra_label_price` keeps buying
and pays per label on the next invoice (app/billing/nightly.py); a plan without one stops.
"""

from decimal import Decimal

PLANS = {
    "free": {"labels_per_month": 50, "assistant": False, "extra_label_price": None},
    "starter": {"labels_per_month": 1_000, "assistant": True, "extra_label_price": Decimal("0.08")},
    "growth": {"labels_per_month": None, "assistant": True, "extra_label_price": None},
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
