"""Tests for confluence error hierarchy."""

from __future__ import annotations

import pytest

from server.lib.errors import (
    AuthError,
    ConfigError,
    ConfluenceError,
    NotFoundError,
    RateLimitError,
    ServerError,
    SpaceNotAllowedError,
)


def test_all_errors_inherit_from_confluence_error() -> None:
    for err_cls in (
        ConfigError,
        AuthError,
        NotFoundError,
        RateLimitError,
        ServerError,
        SpaceNotAllowedError,
    ):
        assert issubclass(err_cls, ConfluenceError)


def test_rate_limit_error_carries_retry_after() -> None:
    err = RateLimitError("rate limited", retry_after=42)
    assert err.retry_after == 42


def test_space_not_allowed_error_carries_space_key() -> None:
    err = SpaceNotAllowedError("DOCS")
    assert err.space_key == "DOCS"
    assert "DOCS" in str(err)


def test_raising_and_catching() -> None:
    with pytest.raises(AuthError):
        raise AuthError("bad creds")
    with pytest.raises(ConfluenceError):
        raise NotFoundError("page 42 missing")
