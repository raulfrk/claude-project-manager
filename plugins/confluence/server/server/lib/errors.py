"""Confluence plugin exception hierarchy."""

from __future__ import annotations


class ConfluenceError(Exception):
    """Base error for the Confluence plugin."""


class ConfigError(ConfluenceError):
    """Invalid or missing configuration."""


class AuthError(ConfluenceError):
    """401/403 from Confluence."""


class NotFoundError(ConfluenceError):
    """404 from Confluence."""


class RateLimitError(ConfluenceError):
    """429 from Confluence after retries exhausted."""

    def __init__(self, message: str, retry_after: int | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ServerError(ConfluenceError):
    """5xx from Confluence."""


class SpaceNotAllowedError(ConfluenceError):
    """Caller referenced a space key not in allowed_spaces."""

    def __init__(self, space_key: str) -> None:
        super().__init__(f"Space not allowed: {space_key}")
        self.space_key = space_key
