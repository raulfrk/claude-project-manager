"""Exponential backoff with jitter for external API retries."""

from __future__ import annotations

import random


def exponential_backoff(attempt: int, base: float = 1.0, max_delay: float = 30.0) -> float:
    """Calculate delay with jitter: min(base * 2^attempt + random(0,1), max_delay)."""
    delay: float = min(base * (2**attempt) + random.random(), max_delay)
    return delay
