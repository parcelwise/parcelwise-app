"""Plans. Prices live in Stripe; this file only holds what the app enforces."""

PLANS = {
    "free": {"labels_per_month": 50},
    "starter": {"labels_per_month": 1_000},
    "growth": {"labels_per_month": None},
}


def monthly_allowance(plan: str) -> int | None:
    """None means unlimited."""
    return PLANS[plan]["labels_per_month"]


def within_allowance(plan: str, used_this_month: int) -> bool:
    allowance = monthly_allowance(plan)
    return allowance is None or used_this_month < allowance


def labels_left(plan: str, used_this_month: int) -> int | None:
    """Labels the merchant can still buy this month. None means unlimited."""
    allowance = monthly_allowance(plan)
    return None if allowance is None else max(allowance - used_this_month, 0)


def how_many_fit(plan: str, used_this_month: int, requested: int) -> int:
    """For a bulk buy: how many of `requested` labels fit in what's left this month.

    A bulk buy buys as many as fit, in the order shown, and offers the upgrade for the rest
    (Priya Shah, 2026-11-02). A single purchase still refuses outright via within_allowance().
    """
    left = labels_left(plan, used_this_month)
    return requested if left is None else min(requested, left)
