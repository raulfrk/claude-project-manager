"""MCP tool for firing registered hooks."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
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

_DEFAULT_SERVER_PORTS: dict[str, int] = {
    "hooks": 19100,
    "perms": 19101,
    "proj": 19102,
    "worktree": 19103,
    "trello": 19104,
    "jira": 19105,
    "todoist": 19106,
    "zoxide": 19107,
}

_SOCKET_REGISTRY_DIR = Path.home() / ".claude" / "sockets"

# Keep references to non-blocking background tasks to prevent GC
_background_tasks: set[asyncio.Task] = set()


def _resolve_server_url(server_name: str, hooks_port: int) -> str | None:
    """Resolve the URL for a plugin server.

    In Unix mode (default): reads ~/.claude/sockets/{server_name} for the
    current session's PID-tagged socket path.
    In TCP mode: uses the default port mapping.
    Returns None if the server is not reachable (registry missing).
    """
    transport_mode = os.environ.get("HOOK_TRANSPORT", "unix").lower()
    if transport_mode == "tcp":
        port = _DEFAULT_SERVER_PORTS.get(server_name, hooks_port)
        return f"http://127.0.0.1:{port}/hook"

    # Unix mode: read registry file
    registry_file = _SOCKET_REGISTRY_DIR / server_name
    try:
        path = registry_file.read_text().strip()
        if path:
            return f"unix://{path}"
    except (FileNotFoundError, OSError):
        pass
    return None


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
    url = _resolve_server_url(hook.server, registry.settings.get("hooks_port", 19100))
    if not url:
        logger.warning("No URL registered for server %r, skipping", hook.server)
        return FireResult(hook_id=hook.id, status_code=0, body="", error=f"No URL for server {hook.server!r}")

    return await post_hook(
        hook_id=hook.id,
        url=url,
        target_tool=hook.target_tool,
        params=params,
    )


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
            storage.log_invocation(
                hook_id=hook.id,
                trigger_tool=hook.trigger_tool,
                target_tool=hook.target_tool,
                server=hook.server,
                source_result=raw_source_result,
            )

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


async def _launch_nonblocking(hook: Hook, source: dict[str, Any], source_result: str) -> None:
    """Fire a non-blocking hook and log the result without awaiting."""
    try:
        result = await _fire_single(hook, source)
        if result.ok:
            storage.log_invocation(
                hook_id=hook.id,
                trigger_tool=hook.trigger_tool,
                target_tool=hook.target_tool,
                server=hook.server,
                source_result=source_result,
            )
        else:
            err_msg = result.error or f"HTTP {result.status_code}"
            storage.log_failure(
                hook_id=hook.id,
                trigger_tool=hook.trigger_tool,
                target_tool=hook.target_tool,
                server=hook.server,
                error=err_msg,
                source_result=source_result,
            )
    except Exception as exc:
        storage.log_failure(
            hook_id=hook.id,
            trigger_tool=hook.trigger_tool,
            target_tool=hook.target_tool,
            server=hook.server,
            error=str(exc),
            source_result=source_result,
        )


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

    All matched hooks are awaited concurrently and their results are included
    in the response.
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
            "parent_todoist_task_id",
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

    non_blocking_hooks: list[Hook] = []

    for hook in primary_matched:
        if not evaluate_condition(hook.condition, config=base_config):
            skipped += 1
            continue
        if hook.blocking:
            blocking_hooks.append(hook)
        else:
            non_blocking_hooks.append(hook)

    # Phase 1: Blocking hooks — await all concurrently
    results_by_id: dict[str, str | None] = {}
    if blocking_hooks:
        results = await asyncio.gather(
            *[_fire_single(h, source) for h in blocking_hooks],
            return_exceptions=True,
        )
        for hook, result in zip(blocking_hooks, results):
            fired += 1
            if isinstance(result, BaseException):
                err_msg = f"Exception: {result}"
                errors.append({"hook_id": hook.id, "error": err_msg, "target_tool": hook.target_tool})
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
                errors.append({"hook_id": hook.id, "error": err_msg, "target_tool": hook.target_tool})
                storage.log_failure(
                    hook_id=hook.id,
                    trigger_tool=hook.trigger_tool,
                    target_tool=hook.target_tool,
                    server=hook.server,
                    error=err_msg,
                    source_result=source_result,
                )
            else:
                results_by_id[hook.id] = result.result
                storage.log_invocation(
                    hook_id=hook.id,
                    trigger_tool=hook.trigger_tool,
                    target_tool=hook.target_tool,
                    server=hook.server,
                    source_result=source_result,
                )

    # Phase 1.5: Feedback writeback for blocking hooks
    feedback_results: list[dict[str, Any]] = []
    if blocking_hooks and results_by_id:
        for hook in blocking_hooks:
            if not hook.feedback_mapping or not hook.feedback_tool:
                continue
            raw_result = results_by_id.get(hook.id)
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

            # Add source entity IDs for writeback context — include both so
            # the feedback tool (e.g. todo_update) has full project context.
            if "todo_id" in source:
                feedback_params["todo_id"] = source["todo_id"]
            if "project_name" in source:
                feedback_params["project_name"] = source["project_name"]

            # Call feedback tool on the trigger's server (proj)
            trigger_url = _resolve_server_url("proj", registry.settings.get("hooks_port", 19100))
            if trigger_url:
                try:
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
                    if not fb_result.ok:
                        err_msg = fb_result.error or f"HTTP {fb_result.status_code}"
                        storage.log_failure(
                            hook_id=f"{hook.id}-feedback",
                            trigger_tool=hook.trigger_tool,
                            target_tool=hook.feedback_tool,
                            server=hook.server,
                            error=err_msg,
                            source_result=source_result,
                        )
                        errors.append({
                            "hook_id": f"{hook.id}-feedback",
                            "error": err_msg,
                            "target_tool": hook.feedback_tool,
                        })
                except Exception as exc:
                    err_msg = f"feedback writeback exception for {hook.id}: {exc}"
                    feedback_results.append({
                        "hook_id": hook.id,
                        "feedback_tool": hook.feedback_tool,
                        "ok": False,
                        "error": str(exc),
                    })
                    storage.log_failure(
                        hook_id=f"{hook.id}-feedback",
                        trigger_tool=hook.trigger_tool,
                        target_tool=hook.feedback_tool,
                        server=hook.server,
                        error=err_msg,
                        source_result=source_result,
                    )
                    errors.append({
                        "hook_id": f"{hook.id}-feedback",
                        "error": err_msg,
                        "target_tool": hook.feedback_tool,
                    })

    # Schedule non-blocking hooks (fire-and-forget)
    for hook in non_blocking_hooks:
        task = asyncio.create_task(_launch_nonblocking(hook, source, source_result))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    # Phase 2: Fire verification hooks with enriched source_result
    verification_results: list[dict[str, Any]] = []
    if verification_matched:
        # Build hook_results dict from Phase 1 blocking results
        hook_results: dict[str, Any] = dict(results_by_id)

        enriched = {**source, "hook_results": hook_results}
        verification_results = await _fire_verification(
            verification_matched, enriched, trigger_tool, source_result, base_config,
        )

    target_tool_by_id = {hook.id: hook.target_tool for hook in blocking_hooks}
    summary: dict[str, Any] = {
        "hooks_fired": fired,
        "skipped": skipped,
        "errors": errors,
        "results": [
            {"hook_id": k, "result": v, "target_tool": target_tool_by_id.get(k)}
            for k, v in results_by_id.items()
        ],
        "depth": depth,
        "max_depth": max_depth,
        "non_blocking_dispatched": len(non_blocking_hooks),
        "top_level": depth == 0,
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
            "Blocking hooks are awaited concurrently; non-blocking hooks are "
            "dispatched as background tasks and do not delay the response. "
            "Returns JSON summary: {hooks_fired, skipped, errors, non_blocking_dispatched, depth, max_depth}."
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
