"""Tests for wiki_lock W1 fix: anyio.Lock + LOCK_NB + WikiLockTimeoutError."""

from __future__ import annotations


class TestExceptionClasses:
    def test_wiki_lock_timeout_error_importable(self) -> None:
        from server.lib.storage import WikiLockTimeoutError

        assert issubclass(WikiLockTimeoutError, RuntimeError)

    def test_wiki_lock_reentry_error_importable(self) -> None:
        from server.lib.storage import WikiLockReentryError

        assert issubclass(WikiLockReentryError, RuntimeError)

    def test_constants_default(self) -> None:
        from server.lib.storage import WIKI_LOCK_RETRY_INTERVAL, WIKI_LOCK_TIMEOUT

        assert WIKI_LOCK_TIMEOUT == 30.0
        assert WIKI_LOCK_RETRY_INTERVAL == 0.1
