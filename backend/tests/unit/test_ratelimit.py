"""Failed sign-in throttling."""

from __future__ import annotations

from app.core.ratelimit import LoginThrottle


class Clock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_blocks_after_max_failures_then_frees_after_the_window() -> None:
    clock = Clock()
    th = LoginThrottle(max_failures=3, window_s=60, clock=clock)
    for _ in range(3):
        assert th.retry_after("alice", "10.0.0.1") is None
        th.failed("alice", "10.0.0.1")
    wait = th.retry_after("alice", "10.0.0.1")
    assert wait is not None
    assert 1 <= wait <= 61
    clock.t += 61
    assert th.retry_after("alice", "10.0.0.1") is None


def test_keys_are_per_user_and_address_and_success_clears() -> None:
    th = LoginThrottle(max_failures=2, window_s=60, clock=Clock())
    th.failed("Alice", "a")
    th.failed("alice", "a")  # usernames are case-insensitive
    assert th.retry_after("ALICE", "a") is not None
    assert th.retry_after("alice", "b") is None  # another address is not locked out
    assert th.retry_after("bob", "a") is None
    th.succeeded("alice", "a")
    assert th.retry_after("alice", "a") is None


def test_memory_is_bounded() -> None:
    th = LoginThrottle(max_failures=1, window_s=60, clock=Clock(), max_keys=50)
    for i in range(500):
        th.failed(f"user{i}", "a")
    assert len(th._failures) <= 51
