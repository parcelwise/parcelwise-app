from app.billing.plans import within_allowance


def test_free_plan_allowance():
    assert within_allowance("free", 49)
    assert not within_allowance("free", 50)


def test_growth_is_unlimited():
    assert within_allowance("growth", 10_000)
