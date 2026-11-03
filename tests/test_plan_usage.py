from datetime import date

from app.billing.plan_usage import plan_usage
from app.usage.daily import DailyCount
from tests.test_usage_daily import FakeUsage


def test_plan_page_shows_completed_answers_against_the_allowance():
    rows = [
        DailyCount(date(2026, 12, 2), "m1", "labels", 30),
        DailyCount(date(2026, 12, 2), "m1", "assistant", 90),  # attempts: our cost, not shown
        DailyCount(date(2026, 12, 2), "m1", "assistant_answers", 60),
    ]
    assert plan_usage(FakeUsage(rows), "m1", "starter", date(2026, 12, 3)) == {
        "labels": 30,
        "labelsAllowance": 1_000,
        "assistant": 60,
        "assistantAllowance": 500,
    }


def test_growth_labels_are_unlimited_but_answers_are_not():
    usage = plan_usage(FakeUsage([]), "m3", "growth", date(2026, 12, 3))
    assert usage["labelsAllowance"] is None and usage["assistantAllowance"] == 500
