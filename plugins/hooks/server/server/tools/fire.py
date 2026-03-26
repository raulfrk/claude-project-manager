"""MCP tool for firing registered hooks."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from server.lib import storage
from server.lib.conditions import evaluate_condition
from server.lib.http_client import FireResult, post_hook
from server.lib.models import Hook
from server.lib.template import resolve_mapping

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger(__name__)

DEFAULT_MAX_DEPTH = 3


def _get_max_depth() -> int:
    """Read max_depth from hooks.yaml settings, falling back to DEFAULT_MAX_DEPTH."""
    registry = storage.load()
    settings = registry.settings
    if isinstance(settings, dict):
        md = settings.get("max_depth")
        if isinstance(md, int) and md > 0:
            return md
    return DEFAULT_MAX_DEPTH


# ── Core fire logic ──────────────────────────────────────────────────────────


async def _fire_single(hook: Hook, source: dict[str, Any]) -> FireResult:
    """Resolve params and POST a single hook."""
    params = resolve_mapping(hook.param_mapping, source)

    registry = storage.load()
    server_info = registry.servers.get(hook.server, {})
    url = server_info.get("url")
    if not url:
        logger.warning("No URL registered for server %r, using name as fallback", hook.server)
        url = hook.server

    return await post_hook(
        hook_id=hook.id,
        url=url,
        target_tool=hook.target_tool,
        params=params,
    )


def _fire_background(hook: Hook, source: dict[str, Any]) -> None:
    """Launch a fire-and-forget task for *hook* in a background thread."""

    async def _run() -> None:
        result = await _fire_single(hook, source)
        if not result.ok:
            storage.log_failure(
                hook_id=hook.id,
                trigger_tool=hook.trigger_tool,
                target_tool=hook.target_tool,
                server=hook.server,
                error=result.error or f"HTTP {result.status_code}",
                source_result=json.dumps(source),
            )

    def _thread_target() -> None:
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(_run())
        finally:
            loop.close()

    import threading

    t = threading.Thread(target=_thread_target, daemon=True)
    t.start()


# ── Tool function ────────────────────────────────────────────────────────────


async def hooks_fire(
    trigger_tool: str,
    source_result: str = "{}",
    _depth: int = 0,
) -> str:
    """Fire all hooks registered for *trigger_tool*.

    *source_result* is a JSON string representing the output of the trigger tool.
    Template ``${}`` placeholders in each hook's ``param_mapping`` are resolved
    against the parsed *source_result*.

    *_depth* tracks the current cascade level.  When it reaches *max_depth*
    (default 3, configurable via ``settings.max_depth`` in hooks.yaml) the call
    is skipped with a warning to prevent runaway cascading.

    Hooks with ``blocking=False`` (default) are dispatched in background threads
    and the tool returns immediately.  Hooks with ``blocking=True`` are awaited
    and their results are included in the response.
    """
    # Runtime depth limit
    max_depth = _get_max_depth()
    if _depth >= max_depth:
        msg = (
            f"Hook depth limit reached ({_depth}/{max_depth}) for trigger "
            f"'{trigger_tool}'. Skipping to prevent runaway cascade."
        )
        logger.warning(msg)
        return json.dumps({
            "hooks_fired": 0,
            "skipped": 0,
            "errors": [],
            "depth_limited": True,
            "depth": _depth,
            "max_depth": max_depth,
            "message": msg,
        })

    # Parse source_result
    try:
        source: dict[str, Any] = json.loads(source_result)
        if not isinstance(source, dict):
            return "Error: source_result must be a JSON object, got " + type(source).__name__
    except json.JSONDecodeError as e:
        return f"Error: source_result is not valid JSON: {e}"

    registry = storage.load()
    matched = [h for h in registry.hooks if h.trigger_tool == trigger_tool]

    if not matched:
        return json.dumps({"hooks_fired": 0, "skipped": 0, "errors": [], "depth": _depth})

    fired = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    blocking_hooks: list[Hook] = []
    background_hooks: list[Hook] = []

    for hook in matched:
        if not evaluate_condition(hook.condition):
            skipped += 1
            continue
        if hook.blocking:
            blocking_hooks.append(hook)
        else:
            background_hooks.append(hook)

    # Fire-and-forget hooks
    for hook in background_hooks:
        _fire_background(hook, source)
        fired += 1

    # Blocking hooks — await all concurrently
    blocking_results: list[dict[str, str | None]] = []
    if blocking_hooks:
        results = await asyncio.gather(
            *[_fire_single(h, source) for h in blocking_hooks],
            return_exceptions=True,
        )
        for hook, result in zip(blocking_hooks, results):
            fired += 1
            if isinstance(result, BaseException):
                err_msg = f"Exception: {result}"
                errors.append({"hook_id": hook.id, "error": err_msg})
                storage.log_failure(
                    hook_id=hook.id,
                    trigger_tool=hook.trigger_tool,
                    target_tool=hook.target_tool,
                    server=hook.server,
                    error=err_msg,
                    source_result=source_result,
                )
            elif not result.ok:
                err_msg = result.error or f"HTTP {result.status_code}"
                errors.append({"hook_id": hook.id, "error": err_msg})
                storage.log_failure(
                    hook_id=hook.id,
                    trigger_tool=hook.trigger_tool,
                    target_tool=hook.target_tool,
                    server=hook.server,
                    error=err_msg,
                    source_result=source_result,
                )
            else:
                blocking_results.append({"hook_id": hook.id, "result": result.result})

    summary: dict[str, Any] = {
        "hooks_fired": fired,
        "skipped": skipped,
        "errors": errors,
        "results": blocking_results,
        "depth": _depth,
        "max_depth": max_depth,
    }
    return json.dumps(summary, indent=2)


# ── Registration ─────────────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register the hooks_fire tool with the MCP application."""

    @app.tool(
        description=(
            "Fire all hooks registered for a given trigger_tool. "
            "source_result is a JSON string of the trigger tool's output used to "
            "resolve ${} template placeholders in each hook's param_mapping. "
            "_depth tracks the current cascade level (default 0); calls are "
            "skipped when depth >= max_depth (default 3, configurable in "
            "hooks.yaml settings.max_depth). "
            "Fire-and-forget hooks return immediately; blocking hooks are awaited. "
            "Returns JSON summary: {hooks_fired, skipped, errors, depth, max_depth}."
        )
    )
    async def hooks_fire_tool(
        trigger_tool: str,
        source_result: str = "{}",
        _depth: int = 0,
    ) -> str:
        return await hooks_fire(
            trigger_tool=trigger_tool,
            source_result=source_result,
            _depth=_depth,
        )
