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
