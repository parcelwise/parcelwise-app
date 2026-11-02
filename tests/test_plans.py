from app.billing.plans import how_many_fit, labels_left, within_allowance


def test_free_plan_allowance():
    assert within_allowance("free", 49)
    assert not within_allowance("free", 50)


def test_growth_is_unlimited():
    assert within_allowance("growth", 10_000)


def test_labels_left():
    assert labels_left("free", 40) == 10
    assert labels_left("free", 60) == 0
    assert labels_left("growth", 10_000) is None


def test_bulk_buys_as_many_as_fit():
    assert how_many_fit("starter", 900, 200) == 100
    assert how_many_fit("starter", 800, 200) == 200
    assert how_many_fit("starter", 1_000, 200) == 0
    assert how_many_fit("growth", 50_000, 200) == 200
