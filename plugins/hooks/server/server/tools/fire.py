"""MCP tool for firing registered hooks."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING, Any

from server.lib import storage
from server.lib.conditions import evaluate_condition, _load_proj_config
from server.lib.http_client import FireResult, post_hook
from server.lib.models import Hook
from server.lib.template import _resolve_path, resolve_mapping

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


# ── Verification helpers ─────────────────────────────────────────────────────


def _parse_verification_response(raw_result: str | None) -> tuple[str, str]:
    """Parse a convention-based verification response.

    Expected format: ``{"status": "pass|fail", "details": "..."}``

    Returns ``(status, details)``.  Missing ``status`` field → fail.
    """
    if raw_result is None:
        return "fail", "no response"
    try:
        data = json.loads(raw_result)
    except (json.JSONDecodeError, TypeError):
        return "fail", str(raw_result)
    if isinstance(data, dict) and "status" in data:
        return str(data["status"]), str(data.get("details", ""))
    # Malformed — missing status field
    return "fail", str(raw_result)


async def _fire_verification(
    hooks: list[Hook],
    enriched_source: dict[str, Any],
    trigger_tool: str,
    raw_source_result: str,
    config: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Fire verification hooks (Phase 2).  All are blocking.

    Each result is parsed for convention-based ``{"status", "details"}``
    and stored via ``storage.store_verification_result()``.

    Verification hooks do NOT increment depth (cannot trigger other hooks).
    """
    results: list[dict[str, Any]] = []

    # Filter by condition
    eligible = [h for h in hooks if evaluate_condition(h.condition, config=config)]

    if not eligible:
        return results

    fire_results = await asyncio.gather(
        *[_fire_single(h, enriched_source) for h in eligible],
        return_exceptions=True,
    )

    for hook, result in zip(eligible, fire_results):
        if isinstance(result, BaseException):
            status, details = "fail", f"Exception: {result}"
            storage.log_failure(
                hook_id=hook.id,
                trigger_tool=hook.trigger_tool,
                target_tool=hook.target_tool,
                server=hook.server,
                error=details,
                source_result=raw_source_result,
            )
        elif not result.ok:
            err_msg = result.error or f"HTTP {result.status_code}"
            status, details = "fail", err_msg
            storage.log_failure(
                hook_id=hook.id,
                trigger_tool=hook.trigger_tool,
                target_tool=hook.target_tool,
                server=hook.server,
                error=err_msg,
                source_result=raw_source_result,
            )
        else:
            status, details = _parse_verification_response(result.result)

        storage.store_verification_result(
            trigger_tool=trigger_tool,
            hook_id=hook.id,
            status=status,
            details=details,
        )
        results.append({
            "hook_id": hook.id,
            "status": status,
            "details": details,
        })

    return results


# ── Tool function ────────────────────────────────────────────────────────────


async def hooks_fire(
    trigger_tool: str,
    source_result: str = "{}",
    depth: int = 0,
) -> str:
    """Fire all hooks registered for *trigger_tool*.

    *source_result* is a JSON string representing the output of the trigger tool.
    Template ``${}`` placeholders in each hook's ``param_mapping`` are resolved
    against the parsed *source_result*.

    *depth* tracks the current cascade level.  When it reaches *max_depth*
    (default 3, configurable via ``settings.max_depth`` in hooks.yaml) the call
    is skipped with a warning to prevent runaway cascading.

    Hooks with ``blocking=False`` (default) are dispatched in background threads
    and the tool returns immediately.  Hooks with ``blocking=True`` are awaited
    and their results are included in the response.
    """
    # Runtime depth limit
    max_depth = _get_max_depth()
    if depth >= max_depth:
        msg = (
            f"Hook depth limit reached ({depth}/{max_depth}) for trigger "
            f"'{trigger_tool}'. Skipping to prevent runaway cascade."
        )
        logger.warning(msg)
        return json.dumps({
            "hooks_fired": 0,
            "skipped": 0,
            "errors": [],
            "depth_limited": True,
            "depth": depth,
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

    # Build merged config for condition evaluation
    base_config = _load_proj_config()
    if source:
        # Inject todo-level fields
        todo_fields = {k: v for k, v in source.items() if k in (
            "todoist_task_id", "trello_card_id", "trello_checklist_id",
            "trello_checklist_item_id", "jira_issue_key",
        )}
        if todo_fields:
            base_config.setdefault("todo", {}).update(todo_fields)
        # Inject project-level fields
        project_fields = {k: v for k, v in source.items() if k in (
            "todoist_project_id", "trello_card_id", "trello_checklist_id",
        )}
        if project_fields:
            base_config.setdefault("project", {}).update(project_fields)

    registry = storage.load()
    matched = [h for h in registry.hooks if h.trigger_tool == trigger_tool]

    if not matched:
        return json.dumps({"hooks_fired": 0, "skipped": 0, "errors": [], "depth": depth})

    # Split into primary and verification hooks
    primary_matched = [h for h in matched if not h.verification]
    verification_matched = [h for h in matched if h.verification]

    fired = 0
    skipped = 0
    errors: list[dict[str, str]] = []
    blocking_hooks: list[Hook] = []
    background_hooks: list[Hook] = []

    for hook in primary_matched:
        if not evaluate_condition(hook.condition, config=base_config):
            skipped += 1
            continue
        if hook.blocking:
            blocking_hooks.append(hook)
        else:
            background_hooks.append(hook)

    # Phase 1: Fire-and-forget hooks
    for hook in background_hooks:
        _fire_background(hook, source)
        fired += 1

    # Phase 1: Blocking hooks — await all concurrently
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

    # Phase 1.5: Feedback writeback for blocking hooks
    feedback_results: list[dict[str, Any]] = []
    if blocking_hooks and blocking_results:
        for hook, br in zip(blocking_hooks, blocking_results):
            if not hook.feedback_mapping or not hook.feedback_tool:
                continue
            raw_result = br.get("result")
            if not raw_result:
                continue
            try:
                result_data = json.loads(raw_result) if isinstance(raw_result, str) else raw_result
            except (json.JSONDecodeError, TypeError):
                continue

            feedback_params: dict[str, Any] = {}
            for result_path, target_param in hook.feedback_mapping.items():
                value = _resolve_path(result_data, result_path)
                if value is not None:
                    feedback_params[target_param] = value

            if not feedback_params:
                continue

            # Add source entity ID for writeback context
            if "todo_id" in source:
                feedback_params["todo_id"] = source["todo_id"]
            elif "project_name" in source:
                feedback_params["project_name"] = source["project_name"]

            # Call feedback tool on the trigger's server (proj)
            trigger_server_info = registry.servers.get("proj", {})
            trigger_url = trigger_server_info.get("url")
            if trigger_url:
                fb_result = await post_hook(
                    hook_id=f"{hook.id}-feedback",
                    url=trigger_url,
                    target_tool=hook.feedback_tool,
                    params=feedback_params,
                )
                feedback_results.append({
                    "hook_id": hook.id,
                    "feedback_tool": hook.feedback_tool,
                    "ok": fb_result.ok,
                    "error": fb_result.error,
                })

    # Phase 2: Fire verification hooks with enriched source_result
    verification_results: list[dict[str, Any]] = []
    if verification_matched:
        # Build hook_results dict from Phase 1 blocking results
        hook_results: dict[str, Any] = {}
        for br in blocking_results:
            hook_results[br["hook_id"]] = br["result"]  # type: ignore[index]

        enriched = {**source, "hook_results": hook_results}
        verification_results = await _fire_verification(
            verification_matched, enriched, trigger_tool, source_result, base_config,
        )

    summary: dict[str, Any] = {
        "hooks_fired": fired,
        "skipped": skipped,
        "errors": errors,
        "results": blocking_results,
        "depth": depth,
        "max_depth": max_depth,
    }
    if verification_results:
        summary["verification"] = verification_results
    if feedback_results:
        summary["feedback"] = feedback_results
    return json.dumps(summary, indent=2)


# ── Registration ─────────────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register the hooks_fire tool with the MCP application."""

    @app.tool(
        description=(
            "Fire all hooks registered for a given trigger_tool. "
            "source_result is a JSON string of the trigger tool's output used to "
            "resolve ${} template placeholders in each hook's param_mapping. "
            "depth tracks the current cascade level (default 0); calls are "
            "skipped when depth >= max_depth (default 3, configurable in "
            "hooks.yaml settings.max_depth). "
            "Fire-and-forget hooks return immediately; blocking hooks are awaited. "
            "Returns JSON summary: {hooks_fired, skipped, errors, depth, max_depth}."
        )
    )
    async def hooks_fire_tool(
        trigger_tool: str,
        source_result: str = "{}",
        depth: int = 0,
    ) -> str:
        return await hooks_fire(
            trigger_tool=trigger_tool,
            source_result=source_result,
            depth=depth,
        )
