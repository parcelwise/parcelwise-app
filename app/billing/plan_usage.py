"""What the Plan page shows (web/settings/PlanUsage.tsx): this month's usage against the plan.

Assistant answers are the billable count (completed answers, one per request id), not attempts, shown as N of M
with the per-answer price past the allowance. No estimated charge until merchants have seen a real invoice
(Priya, Raven task afdabadc60bd).
"""

from datetime import date

from app.billing.plans import PLANS
from app.usage.daily import ASSISTANT_ANSWERS, month_to_date


def plan_usage(usage, merchant_id: str, plan: str, today: date) -> dict:
    used = month_to_date(usage, merchant_id, today, features={"labels", ASSISTANT_ANSWERS})
    entry = PLANS[plan]
    price = entry["extra_assistant_answer_price"]
    return {
        "labels": used["labels"],
        "labelsAllowance": entry["labels_per_month"],
        "assistantAnswers": used[ASSISTANT_ANSWERS],
        "assistantAllowance": entry["assistant_answers_per_month"],
        "assistantPrice": None if price is None else str(price),  # Decimal as a string, never a float
    }
