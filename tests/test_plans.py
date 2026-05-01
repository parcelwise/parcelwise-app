from app.billing.plans import within_allowance


def test_free_plan_allowance():
    assert within_allowance("free", 49)
    assert not within_allowance("free", 50)


def test_growth_is_unlimited():
    assert within_allowance("growth", 10_000)


def test_free_has_no_assistant():
    from app.billing.plans import has_assistant

    assert not has_assistant("free")
    assert has_assistant("starter") and has_assistant("growth")
