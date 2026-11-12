import pytest

from app.ratelimit import SlidingWindowLimiter
from app.settings import RateLimit


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def make(limit: int, window: float, clock: Clock, max_keys: int = 10_000) -> SlidingWindowLimiter:
    return SlidingWindowLimiter(RateLimit(limit=limit, window_seconds=window), clock, max_keys)


def test_requests_up_to_the_limit_pass_and_the_next_is_refused() -> None:
    clock = Clock()
    limiter = make(3, 60, clock)

    assert [limiter.hit("a").allowed for _ in range(3)] == [True, True, True]
    refused = limiter.hit("a")
    assert not refused.allowed
    assert refused.retry_after == pytest.approx(60)


def test_retry_after_is_when_the_oldest_request_leaves_the_window() -> None:
    clock = Clock()
    limiter = make(2, 60, clock)
    limiter.hit("a")
    clock.now += 20
    limiter.hit("a")
    clock.now += 10

    assert limiter.hit("a").retry_after == pytest.approx(30)

    clock.now += 30  # the first request is now exactly one window old
    assert limiter.hit("a").allowed
    assert not limiter.hit("a").allowed  # the second one still counts


def test_refused_requests_do_not_extend_the_block() -> None:
    clock = Clock()
    limiter = make(1, 60, clock)
    limiter.hit("a")
    for _ in range(10):
        clock.now += 5
        limiter.hit("a")  # hammering while blocked
    clock.now += 10  # 60 s after the one accepted request
    assert limiter.hit("a").allowed


def test_keys_are_limited_independently() -> None:
    clock = Clock()
    limiter = make(1, 60, clock)
    assert limiter.hit("a").allowed
    assert limiter.hit("b").allowed
    assert not limiter.hit("a").allowed


def test_memory_is_bounded_when_many_keys_appear() -> None:
    clock = Clock()
    limiter = make(1, 60, clock, max_keys=100)
    for i in range(100):
        limiter.hit(f"old-{i}")
    clock.now += 61  # all of them are idle now
    limiter.hit("new")
    assert len(limiter) == 1

    for i in range(1000):  # a flood of distinct, active keys
        limiter.hit(f"flood-{i}")
    assert len(limiter) <= 100
