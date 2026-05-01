"""Plans. Prices live in Stripe; this file only holds what the app enforces."""

PLANS = {
    "free": {"labels_per_month": 50, "assistant": False},
    "starter": {"labels_per_month": 1_000, "assistant": True},
    "growth": {"labels_per_month": None, "assistant": True},
}


def monthly_allowance(plan: str) -> int | None:
    """None means unlimited."""
    return PLANS[plan]["labels_per_month"]


def within_allowance(plan: str, used_this_month: int) -> bool:
    allowance = monthly_allowance(plan)
    return allowance is None or used_this_month < allowance


def has_assistant(plan: str) -> bool:
    """The assistant is part of the paid plans; Free does not get it (Priya, #55)."""
    return PLANS[plan]["assistant"]
