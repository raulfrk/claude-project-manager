"""Generic secret scrubbing and structured error helpers for hook dispatch.

This module is the single home for redacting credentials out of hook result
strings and for building the `_hooks.structured_errors` sidecar element shape.
`hook_dispatch.dispatch` imports from here so every plugin that wraps tools
benefits from consistent scrubbing and error shape.
"""

from __future__ import annotations

import re
from typing import Any

# Narrow allowlist — matches common bearer-token URL patterns without
# false-positiving UUIDs, task ids, or identifier-looking strings.
_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"([?&]key=)([^&\s]+)"),
    re.compile(r"([?&]token=)([^&\s]+)"),
    re.compile(r"(Authorization:\s*(?:Bearer|Basic)\s+)(\S+)"),
    re.compile(r"(api_token[\"'=:\s]+)([A-Za-z0-9_\-]{8,})"),
    re.compile(r"(password[\"'=:\s]+)([^\s\"']{4,})"),
    re.compile(r"(secret[\"'=:\s]+)([A-Za-z0-9_\-]{8,})"),
)


def _redact(match: re.Match[str]) -> str:
    prefix, secret = match.group(1), match.group(2)
    last4 = secret[-4:] if len(secret) >= 4 else secret
    return f"{prefix}****{last4}"


def scrub_secrets(obj: Any) -> Any:
    """Recursively scrub secret-looking substrings from strings, dicts, and lists.

    Walks dict/list/str inputs and redacts any matches of the pattern
    allowlist. Non-string leaves pass through unchanged. Always returns a
    value of the same shape as the input; never raises.
    """
    if isinstance(obj, str):
        scrubbed = obj
        for pat in _PATTERNS:
            scrubbed = pat.sub(_redact, scrubbed)
        return scrubbed
    if isinstance(obj, dict):
        return {k: scrub_secrets(v) for k, v in obj.items()}  # type: ignore[misc]
    if isinstance(obj, list):
        return [scrub_secrets(v) for v in obj]  # type: ignore[misc]
    return obj


def build_structured_error(
    integration: str,
    failed_ids: list[str],
    exc: Exception | str,
    *,
    target_tool: str = "",
    error_type: str = "",
) -> dict[str, Any]:
    """Build one `_hooks.structured_errors` element with a scrubbed message.

    Parameters
    ----------
    integration:
        Name of the integration plugin (``todoist``, ``trello``, ``jira``).
    failed_ids:
        List of ids (todo/task/card/issue) the integration failed to sync.
    exc:
        Exception instance or pre-formatted error string. Scrubbed before use.
    target_tool:
        Optional MCP tool name that was the failing target.
    error_type:
        Optional classification — one of ``transient``, ``permanent``,
        ``auth``, ``rate_limit``. Defaults to the exception class name.
    """
    if isinstance(exc, Exception):
        message = f"{type(exc).__name__}: {exc}"
        resolved_type = error_type or type(exc).__name__
    else:
        message = str(exc)
        resolved_type = error_type or "error"
    return {
        "integration": integration,
        "target_tool": target_tool,
        "error_type": resolved_type,
        "message": scrub_secrets(message),
        "failed_ids": list(failed_ids),
    }


__all__ = ["build_structured_error", "scrub_secrets"]
