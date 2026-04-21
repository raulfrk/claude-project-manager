"""Token bucket rate limiter for Confluence API calls."""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """Simple token bucket. Capacity tokens refilled over refill_seconds."""

    def __init__(self, capacity: int, refill_seconds: float) -> None:
        self.capacity = capacity
        self.refill_seconds = refill_seconds
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * (self.capacity / self.refill_seconds)
        self._tokens = min(float(self.capacity), self._tokens + added)
        self._last_refill = now

    def try_acquire(self) -> bool:
        with self._lock:
            self._refill()
            if self._tokens >= 1.0:
                self._tokens -= 1.0
                return True
            return False

    def acquire(self) -> None:
        """Block until a token is available."""
        while not self.try_acquire():
            wait = max(0.05, self.refill_seconds / self.capacity)
            time.sleep(wait)
