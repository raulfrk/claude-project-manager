"""Tests for token bucket rate limiter."""

from __future__ import annotations

import time

from server.lib.ratelimit import TokenBucket


def test_initial_bucket_is_full() -> None:
    bucket = TokenBucket(capacity=5, refill_seconds=10.0)
    for _ in range(5):
        assert bucket.try_acquire() is True


def test_acquire_blocks_until_refill() -> None:
    bucket = TokenBucket(capacity=2, refill_seconds=1.0)
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is True
    assert bucket.try_acquire() is False

    time.sleep(0.6)
    assert bucket.try_acquire() is True


def test_acquire_blocking_call() -> None:
    bucket = TokenBucket(capacity=1, refill_seconds=0.5)
    assert bucket.try_acquire() is True

    t0 = time.monotonic()
    bucket.acquire()  # should block ~0.5s
    elapsed = time.monotonic() - t0

    assert 0.3 < elapsed < 0.9


def test_capacity_and_refill_rate_exposed() -> None:
    bucket = TokenBucket(capacity=10, refill_seconds=10.0)
    assert bucket.capacity == 10
    assert bucket.refill_seconds == 10.0
