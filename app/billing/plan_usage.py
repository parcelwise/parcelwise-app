"""What the Plan page shows: this month's usage against what the plan includes (web/settings/PlanUsage.tsx).

Assistant answers are the billable count, one completed answer per question (app/usage/daily.py
ASSISTANT_ANSWERS), so the page shows what the invoice will count, not our attempts.
"""

from datetime import date

from app.billing.plans import PLANS
from app.usage.daily import ASSISTANT_ANSWERS, month_to_date


def plan_usage(usage, merchant_id: str, plan: str, today: date) -> dict:
    counts = month_to_date(usage, merchant_id, today, features={"labels", ASSISTANT_ANSWERS})
    included = PLANS[plan]
    return {
        "labels": counts["labels"],
        "labelsAllowance": included["labels_per_month"],
        "assistant": counts[ASSISTANT_ANSWERS],
        "assistantAllowance": included["assistant_per_month"],
    }
