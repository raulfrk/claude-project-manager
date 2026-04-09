"""Tests for exponential backoff with jitter."""

from __future__ import annotations

from server.lib.backoff import exponential_backoff


class TestExponentialBackoff:
    def test_exponential_growth(self):
        """Delays should grow exponentially (ignoring jitter)."""
        # With base=1.0, delay ~ 1*2^attempt + jitter
        # attempt=0 -> ~1, attempt=1 -> ~2, attempt=2 -> ~4, attempt=3 -> ~8
        for attempt in range(4):
            delay = exponential_backoff(attempt, base=1.0, max_delay=100.0)
            expected_base = 1.0 * (2**attempt)
            # Jitter adds [0, 1), so delay should be in [expected_base, expected_base + 1)
            assert delay >= expected_base
            assert delay < expected_base + 1.0

    def test_max_delay_cap(self):
        """Delay should never exceed max_delay."""
        for attempt in range(20):
            delay = exponential_backoff(attempt, base=1.0, max_delay=5.0)
            assert delay <= 5.0

    def test_jitter_present(self):
        """Multiple calls should produce different values (non-deterministic but within range)."""
        results = {exponential_backoff(0, base=1.0, max_delay=100.0) for _ in range(50)}
        # With jitter, we expect many distinct values (not all identical)
        assert len(results) > 1

    def test_custom_base(self):
        """Custom base should scale the delay."""
        delay = exponential_backoff(0, base=2.0, max_delay=100.0)
        # base=2.0, attempt=0 -> 2.0 * 2^0 + jitter = 2.0 + jitter
        assert delay >= 2.0
        assert delay < 3.0

    def test_zero_attempt(self):
        """Attempt 0 should produce a delay near the base value."""
        delay = exponential_backoff(0, base=0.5, max_delay=100.0)
        # 0.5 * 2^0 + jitter = 0.5 + [0, 1)
        assert delay >= 0.5
        assert delay < 1.5

    def test_max_delay_equals_computed_delay(self):
        """When max_delay exactly equals the computed delay, result should be at most max_delay."""
        # base=4.0, attempt=0 -> 4.0 + jitter(0..1) => cap at 4.0
        delay = exponential_backoff(0, base=4.0, max_delay=4.0)
        assert delay <= 4.0

    def test_large_attempt_saturates_at_max(self):
        """Very large attempt numbers should still return max_delay."""
        delay = exponential_backoff(1000, base=1.0, max_delay=10.0)
        assert delay <= 10.0
