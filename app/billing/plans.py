"""Plans. Prices live in Stripe; this file only holds what the app enforces."""

PLANS = {
    "free": {"labels_per_month": 50},
    "starter": {"labels_per_month": 1_000},
    "growth": {"labels_per_month": None},
}


def monthly_allowance(plan: str) -> int | None:
    """None means unlimited."""
    return PLANS[plan]["labels_per_month"]
