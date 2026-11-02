from app.labels.carriers import PURCHASES_PER_MINUTE
from app.labels.ratelimit import PurchaseRateLimiter


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_usps_is_limited_to_40_a_minute_per_merchant():
    assert PURCHASES_PER_MINUTE["usps"] == 40
    clock = Clock()
    limiter = PurchaseRateLimiter(clock=clock)
    for _ in range(40):
        assert limiter.wait_seconds("bloom", "usps") == 0
        limiter.record("bloom", "usps")
        clock.now += 0.5
    assert limiter.wait_seconds("bloom", "usps") == 40.0
    # Another merchant's account isn't held up by Bloom's batch.
    assert limiter.wait_seconds("other", "usps") == 0
    clock.now = 60.0
    assert limiter.wait_seconds("bloom", "usps") == 0


def test_carriers_without_a_limit_are_not_held():
    limiter = PurchaseRateLimiter(clock=Clock())
    for _ in range(100):
        limiter.record("bloom", "ups")
    assert limiter.wait_seconds("bloom", "ups") == 0
