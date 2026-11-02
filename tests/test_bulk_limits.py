import pytest

from app.labels.bulk import MAX_BATCH_SIZE, MAX_PER_MINUTE, BatchTooLarge, Pacer, check_batch_size


def test_batch_at_the_cap_is_allowed_and_one_over_is_refused():
    check_batch_size(["o"] * MAX_BATCH_SIZE)
    with pytest.raises(BatchTooLarge):
        check_batch_size(["o"] * (MAX_BATCH_SIZE + 1))


def test_pacer_never_starts_more_than_the_limit_in_a_minute():
    now = [0.0]
    starts = []

    def sleep(seconds):
        now[0] += seconds

    pacer = Pacer(clock=lambda: now[0], sleep=sleep)
    for _ in range(MAX_BATCH_SIZE):
        pacer.wait()
        starts.append(now[0])

    assert starts[0] == 0.0
    for i, t in enumerate(starts):
        in_window = [s for s in starts[i:] if s < t + 60.0]
        assert len(in_window) <= MAX_PER_MINUTE
    assert starts[-1] == pytest.approx((MAX_BATCH_SIZE - 1) * 60.0 / MAX_PER_MINUTE)


def test_pacer_does_not_sleep_when_calls_are_already_slow():
    now = [0.0]
    slept = []
    pacer = Pacer(clock=lambda: now[0], sleep=slept.append)
    pacer.wait()
    now[0] += 10.0
    pacer.wait()
    assert slept == []


def test_already_labeled_orders_are_skipped_and_reported_in_order():
    from app.labels.bulk import ALREADY_LABELED, split_already_labeled

    to_buy, skipped = split_already_labeled(["a", "b", "c", "d"], {"b", "d"})
    assert to_buy == ["a", "c"]
    assert skipped == [("b", ALREADY_LABELED), ("d", ALREADY_LABELED)]


def test_live_label_query_ignores_voided_labels_and_returns_a_set():
    from app.labels.bulk import order_ids_with_live_label

    class Conn:
        def execute(self, sql, params):
            assert "voided_at IS NULL" in sql
            assert params == (["a", "b"],)
            return self

        def fetchall(self):
            return [("a",), ("a",)]

    assert order_ids_with_live_label(Conn(), ["a", "b"]) == {"a"}


def test_allowance_refuses_whole_batch_and_reports_what_is_left():
    from app.labels.bulk import AllowanceExceeded, check_allowance

    check_allowance("free", 0, 50)
    check_allowance("growth", 10_000, 200)
    with pytest.raises(AllowanceExceeded) as err:
        check_allowance("free", 10, 41)
    assert err.value.remaining == 40
    with pytest.raises(AllowanceExceeded) as err:
        check_allowance("free", 60, 1)
    assert err.value.remaining == 0
