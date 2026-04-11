"""MCP tool for querying hook invocation history (successes + failures)."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib import storage

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from server.lib._types import JsonValue

_MAX_LIMIT = 200


def hooks_invocations(
    hook_id: str | None = None,
    trigger_tool: str | None = None,
    target_tool: str | None = None,
    type: str = "all",
    limit: int = 50,
) -> str:
    """Return a unified view of hook invocation history.

    Combines successful invocations from hooks-invocations.yaml with failures
    from hooks-failures.yaml. Each entry has a ``_type`` field: "invocation" or "failure".
    Results are sorted newest-first and sliced to ``limit`` (clamped to 200).
    """
    limit = min(limit, _MAX_LIMIT)
    combined: list[dict[str, JsonValue]] = []

    if type in ("invocation", "all"):
        for entry in storage.load_invocations(limit=0):
            combined.append(dict(entry, _type="invocation"))

    if type in ("failure", "all"):
        for entry in storage.load_failures():
            combined.append(dict(entry, _type="failure"))

    # Apply filters
    if hook_id is not None:
        combined = [e for e in combined if e.get("hook_id") == hook_id]
    if trigger_tool is not None:
        combined = [e for e in combined if e.get("trigger_tool") == trigger_tool]
    if target_tool is not None:
        combined = [e for e in combined if e.get("target_tool") == target_tool]

    # Sort newest-first, take limit
    combined.sort(key=lambda e: str(e.get("timestamp", "")), reverse=True)
    combined = combined[:limit]

    return json.dumps(
        {
            "total": len(combined),
            "limit": limit,
            "entries": combined,
        },
        indent=2,
    )


# ── Registration ─────────────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register the hooks_invocations tool with the MCP application."""

    @app.tool(
        description=(
            "Query hook invocation history. Returns a unified view of successful "
            "invocations (~/.claude/hooks-invocations.yaml) and failures "
            "(~/.claude/hooks-failures.yaml). "
            "Each entry includes a _type field: 'invocation' (success) or 'failure'. "
            "Filters: hook_id, trigger_tool, target_tool. "
            "type: 'invocation' (successes only), 'failure' (failures only), 'all' (default). "
            "limit: max entries returned, clamped to 200 (default 50). "
            "Results sorted newest-first."
        )
    )
    def hooks_invocations_tool(
        hook_id: str | None = None,
        trigger_tool: str | None = None,
        target_tool: str | None = None,
        type: str = "all",
        limit: int = 50,
    ) -> str:
        return hooks_invocations(
            hook_id=hook_id,
            trigger_tool=trigger_tool,
            target_tool=target_tool,
            type=type,
            limit=limit,
        )
