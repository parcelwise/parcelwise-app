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


def test_starter_keeps_buying_past_the_allowance_and_free_stops():
    from app.billing.plans import can_buy_label

    assert can_buy_label("starter", 1_000) and can_buy_label("starter", 5_000)
    assert not can_buy_label("free", 50)
    assert can_buy_label("growth", 100_000)
