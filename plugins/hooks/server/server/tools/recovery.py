"""MCP tool for hook failure recovery: list, retry, and clear."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from server.lib._types import JsonValue

from server.lib import storage
from server.lib.http_client import post_hook
from server.lib.template import resolve_mapping

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)


# ── Core logic ───────────────────────────────────────────────────────────────


async def _retry_entry(entry: dict[str, JsonValue]) -> bool:
    """Re-fire a single failure entry using its stored source_result.

    Returns ``True`` on success, ``False`` on failure.
    """
    hook_id = str(entry.get("hook_id", ""))
    target_tool = str(entry.get("target_tool", ""))
    server = str(entry.get("server", ""))
    source_result_raw = str(entry.get("source_result", "{}"))

    # Parse source_result to resolve param_mapping
    try:
        source: dict[str, JsonValue] = json.loads(source_result_raw)
        if not isinstance(source, dict):
            source = {}
    except (json.JSONDecodeError, TypeError):
        source = {}

    # Look up the hook in the registry to get param_mapping
    registry = storage.load()
    hook = registry.find_by_id(hook_id)

    if hook is not None:
        params = resolve_mapping(hook.param_mapping, source)
    else:
        # Hook was unregistered -- fire with empty params
        params = {}

    # Resolve server URL
    server_info = registry.servers.get(server, {})
    url = server_info.get("url", server)

    result = await post_hook(
        hook_id=hook_id,
        url=url,
        target_tool=target_tool,
        params=params,
    )
    return result.ok


async def hooks_recover(
    hook_id: str | None = None,
    clear: bool = False,
) -> str:
    """List, retry, or clear hook failure entries.

    - ``hook_id=None, clear=False`` -- list all failures as a JSON array.
    - ``hook_id="hook-NNN"`` -- retry that hook's failures.
    - ``clear=True`` -- clear all failures without retrying.

    Returns JSON summary with counts: retried, succeeded, still_failed, cleared.
    """
    entries = storage.load_failures()

    # ── Clear mode ───────────────────────────────────────────────────────
    if clear:
        cleared = storage.clear_failures()
        return json.dumps({
            "retried": 0,
            "succeeded": 0,
            "still_failed": 0,
            "cleared": cleared,
        })

    # ── List mode (no hook_id) ───────────────────────────────────────────
    if hook_id is None:
        return json.dumps(entries, indent=2)

    # ── Retry mode (hook_id provided) ────────────────────────────────────
    target_entries = [e for e in entries if e.get("hook_id") == hook_id]
    other_entries = [e for e in entries if e.get("hook_id") != hook_id]

    if not target_entries:
        return json.dumps({
            "retried": 0,
            "succeeded": 0,
            "still_failed": 0,
            "cleared": 0,
            "message": f"No failure entries found for hook_id '{hook_id}'.",
        })

    retried = 0
    succeeded = 0
    still_failed_entries: list[dict[str, JsonValue]] = []

    for entry in target_entries:
        retried += 1
        ok = await _retry_entry(entry)
        if ok:
            succeeded += 1
        else:
            # Increment retry_count and update timestamp
            rc = entry.get("retry_count", 0)
            entry["retry_count"] = (rc if isinstance(rc, int) else 0) + 1
            entry["timestamp"] = datetime.now(tz=timezone.utc).isoformat()
            still_failed_entries.append(entry)

    # Rebuild the failures file: keep others + still-failed retries
    new_entries = other_entries + still_failed_entries
    storage.save_failures(new_entries)

    return json.dumps({
        "retried": retried,
        "succeeded": succeeded,
        "still_failed": len(still_failed_entries),
        "cleared": 0,
    })


# ── Registration ─────────────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register the hooks_recover tool with the MCP application."""

    @app.tool(
        description=(
            "Recover from hook failures. "
            "With no arguments, lists all failure entries as a JSON array. "
            "With hook_id, retries that hook's failures using the stored source_result; "
            "successful retries are removed, failed retries increment retry_count. "
            "With clear=True, removes all failure entries without retrying. "
            "Returns JSON summary: {retried, succeeded, still_failed, cleared}."
        )
    )
    async def hooks_recover_tool(
        hook_id: str | None = None,
        clear: bool = False,
    ) -> str:
        return await hooks_recover(hook_id=hook_id, clear=clear)
