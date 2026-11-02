from datetime import date

from app.billing.plan_usage import plan_usage
from app.usage.daily import ASSISTANT_ANSWERS
from tests.test_usage_daily import FakeUsage, rows_for


def test_plan_page_shows_billable_answers_against_the_allowance_and_the_price():
    usage = FakeUsage(rows_for(["m1"], range(1, 6), count=10)
                      + rows_for(["m1"], range(1, 6), feature="assistant", count=9)  # attempts: not shown
                      + rows_for(["m1"], range(1, 6), feature=ASSISTANT_ANSWERS, count=7))
    assert plan_usage(usage, "m1", "starter", date(2026, 6, 5)) == {
        "labels": 50,
        "labelsAllowance": 1_000,
        "assistantAnswers": 35,
        "assistantAllowance": 200,
        "assistantPrice": "0.04",
    }


def test_growth_allowance_and_free_has_no_price():
    usage = FakeUsage([])
    assert plan_usage(usage, "m1", "growth", date(2026, 6, 5))["assistantAllowance"] == 1_000
    free = plan_usage(usage, "m1", "free", date(2026, 6, 5))
    assert free["assistantAllowance"] is None and free["assistantPrice"] is None
