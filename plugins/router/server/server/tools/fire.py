"""MCP tool for firing registered hooks."""

from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, cast

from server.lib import storage
from server.lib.conditions import _load_proj_config, evaluate_condition
from server.lib.http_client import FireResult, post_hook
from server.lib.template import _resolve_path, resolve_mapping

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from server.lib._types import JsonValue
    from server.lib.models import Hook

logger = logging.getLogger(__name__)

DEFAULT_MAX_DEPTH = 3

_DEFAULT_SERVER_PORTS: dict[str, int] = {
    "hooks": 19100,
    "sandbox": 19101,
    "proj": 19102,
    "worktree": 19103,
    "trello": 19104,
    "jira": 19105,
    "todoist": 19106,
    "zoxide": 19107,
}

_SOCKET_REGISTRY_DIR = Path.home() / ".claude" / "sockets"

# Keep references to non-blocking background tasks to prevent GC
_background_tasks: set[asyncio.Task[None]] = set()


def _resolve_server_url(server_name: str, hooks_port: int) -> str:
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
        if path and os.path.exists(path):
            return f"unix://{path}"
    except (FileNotFoundError, OSError):
        logger.debug("Socket registry lookup failed", exc_info=True)

    # Fallback: glob for newest PID-tagged socket
    prefix = f"/tmp/claude-cpm-{server_name}-"  # noqa: S108
    candidates = sorted(
        glob.glob(f"{prefix}*.sock"),
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )
    if candidates:
        return f"unix://{candidates[0]}"

    # Last resort: use server name as-is (allows direct URL or name-based routing)
    return server_name


def _get_max_depth() -> int:
    """Read max_depth from hooks.yaml settings, falling back to DEFAULT_MAX_DEPTH."""
    registry = storage.load()
    settings = registry.settings
    if isinstance(settings, dict):
        md = settings.get("max_depth")
        if isinstance(md, int) and md > 0:
            return md
    return DEFAULT_MAX_DEPTH


def _evaluate_result_condition(hook: Hook, source: dict[str, JsonValue]) -> bool:
    """Check hook's result_condition against the source result dict.

    Returns True if no result_condition is set, or if all key==value pairs match.
    """
    if hook.result_condition is None:
        return True
    return all(source.get(k) == v for k, v in hook.result_condition.items())


# ── Core fire logic ──────────────────────────────────────────────────────────


async def _fire_single(hook: Hook, source: dict[str, JsonValue]) -> FireResult:
    """Resolve params and POST a single hook."""
    params = resolve_mapping(hook.param_mapping, source)

    registry = storage.load()
    hooks_port = registry.settings.get("hooks_port", 19100)
    port_int = int(hooks_port) if isinstance(hooks_port, (int, float, str)) else 19100
    # Prefer socket registry (PID-tagged, always current) over hooks.yaml servers
    url = _resolve_server_url(hook.server, port_int)
    if url == hook.server:
        # _resolve_server_url fell back to raw name — try hooks.yaml servers
        server_entry = registry.servers.get(hook.server)
        if isinstance(server_entry, dict):
            explicit_url = server_entry.get("url")
            if isinstance(explicit_url, str) and explicit_url:
                url = explicit_url

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
    enriched_source: dict[str, JsonValue],
    trigger_tool: str,
    raw_source_result: str,
    config: dict[str, JsonValue] | None = None,
) -> list[dict[str, JsonValue]]:
    """Fire verification hooks (Phase 2).  All are blocking.

    Each result is parsed for convention-based ``{"status", "details"}``
    and stored via ``storage.store_verification_result()``.

    Verification hooks do NOT increment depth (cannot trigger other hooks).
    """
    results: list[dict[str, JsonValue]] = []

    # Filter by condition
    eligible = [h for h in hooks if evaluate_condition(h.condition, config=config)]

    if not eligible:
        return results

    fire_results = await asyncio.gather(
        *[_fire_single(h, enriched_source) for h in eligible],
        return_exceptions=True,
    )

    for hook, result in zip(eligible, fire_results, strict=False):
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
        results.append(
            {
                "hook_id": hook.id,
                "status": status,
                "details": details,
            }
        )

    return results


async def _launch_nonblocking(hook: Hook, source: dict[str, JsonValue], source_result: str) -> None:
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


# ── Internal fire logic ──────────────────────────────────────────────────────


async def _fire_hooks_internal(
    trigger_tool: str,
    source: dict[str, JsonValue],
    depth: int,
    source_result: str,
    max_depth: int,
    base_config: dict[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    """Core fire logic. Returns a summary dict (not JSON)."""
    if base_config is None:
        base_config = {}

    registry = storage.load()
    matched = [h for h in registry.hooks if h.trigger_tool == trigger_tool]

    if not matched:
        return {"hooks_fired": 0, "skipped": 0, "errors": [], "depth": depth}

    # Split into primary and verification hooks
    primary_matched = [h for h in matched if not h.verification]
    verification_matched = [h for h in matched if h.verification]

    fired = 0
    errors: list[dict[str, JsonValue]] = []
    blocking_hooks: list[Hook] = []
    non_blocking_hooks: list[Hook] = []
    skipped_hooks: list[dict[str, JsonValue]] = []

    for hook in primary_matched:
        if not evaluate_condition(hook.condition, config=base_config):
            skipped_hooks.append(
                {
                    "hook_id": hook.id,
                    "target_tool": hook.target_tool,
                    "reason": f"condition '{hook.condition}' evaluated false",
                }
            )
            continue
        if not _evaluate_result_condition(hook, source):
            logger.debug(
                "Skipping hook %s: result_condition not met (source.result=%s)",
                hook.id,
                source.get("result"),
            )
            skipped_hooks.append(
                {
                    "hook_id": hook.id,
                    "target_tool": hook.target_tool,
                    "reason": f"result_condition {hook.result_condition} not met",
                }
            )
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
        for hook, result in zip(blocking_hooks, results, strict=False):
            fired += 1
            if isinstance(result, BaseException):
                err_msg = f"Exception: {result}"
                errors.append(
                    {"hook_id": hook.id, "error": err_msg, "target_tool": hook.target_tool}
                )
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
                errors.append(
                    {"hook_id": hook.id, "error": err_msg, "target_tool": hook.target_tool}
                )
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
    feedback_results: list[dict[str, JsonValue]] = []
    if blocking_hooks and results_by_id:
        fb_port = registry.settings.get("hooks_port", 19100)
        trigger_url = _resolve_server_url(
            "proj", int(fb_port) if isinstance(fb_port, (int, float, str)) else 19100
        )

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

            # Detect batch feedback: any key containing [*] triggers per-item iteration
            batch_keys = {
                k: v
                for k, v in hook.feedback_mapping.items()
                if isinstance(k, str) and "[*]" in k and isinstance(v, str)
            }

            if batch_keys and trigger_url:
                # Batch feedback: iterate over result array and source created array
                # Key format: "successes[*].id" → array_path="successes", field="id"
                source_created = source.get("created")
                if not isinstance(source_created, list):
                    continue
                for result_path_pattern, target_param in batch_keys.items():
                    parts = result_path_pattern.split("[*].")
                    if len(parts) != 2:
                        continue
                    array_path, field = parts
                    result_array = _resolve_path(result_data, array_path)
                    if not isinstance(result_array, list):
                        continue
                    for i, child_entry in enumerate(source_created):
                        if i >= len(result_array):
                            break  # fewer results than children (partial failure)
                        if not isinstance(child_entry, dict):
                            continue
                        child_id = child_entry.get("id")
                        if not child_id:
                            continue
                        value = (
                            _resolve_path(result_array[i], field)
                            if isinstance(result_array[i], dict)
                            else result_array[i]
                        )
                        if value is None:
                            continue
                        fb_params: dict[str, JsonValue] = {
                            "todo_id": child_id,
                            target_param: value,
                            "skip_hooks": True,
                        }
                        if "project_name" in source:
                            fb_params["project_name"] = source["project_name"]
                        try:
                            fb_result = await post_hook(
                                hook_id=f"{hook.id}-feedback-{i}",
                                url=trigger_url,
                                target_tool=hook.feedback_tool,
                                params=fb_params,
                            )
                            feedback_results.append(
                                {
                                    "hook_id": f"{hook.id}-{i}",
                                    "feedback_tool": hook.feedback_tool,
                                    "ok": fb_result.ok,
                                    "error": fb_result.error,
                                }
                            )
                            if not fb_result.ok:
                                err_msg = fb_result.error or f"HTTP {fb_result.status_code}"
                                storage.log_failure(
                                    hook_id=f"{hook.id}-feedback-{i}",
                                    trigger_tool=hook.trigger_tool,
                                    target_tool=hook.feedback_tool,
                                    server=hook.server,
                                    error=err_msg,
                                    source_result=source_result,
                                )
                                errors.append(
                                    {
                                        "hook_id": f"{hook.id}-feedback-{i}",
                                        "error": err_msg,
                                        "target_tool": hook.feedback_tool,
                                    }
                                )
                        except Exception as exc:
                            err_msg = f"feedback writeback exception for {hook.id}-{i}: {exc}"
                            feedback_results.append(
                                {
                                    "hook_id": f"{hook.id}-{i}",
                                    "feedback_tool": hook.feedback_tool,
                                    "ok": False,
                                    "error": str(exc),
                                }
                            )
                            storage.log_failure(
                                hook_id=f"{hook.id}-feedback-{i}",
                                trigger_tool=hook.trigger_tool,
                                target_tool=hook.feedback_tool,
                                server=hook.server,
                                error=err_msg,
                                source_result=source_result,
                            )
                            errors.append(
                                {
                                    "hook_id": f"{hook.id}-feedback-{i}",
                                    "error": err_msg,
                                    "target_tool": hook.feedback_tool,
                                }
                            )
                continue  # skip single-value path below

            # Single-value feedback (existing behavior)
            feedback_params: dict[str, JsonValue] = {}
            for result_path, target_param in hook.feedback_mapping.items():
                value = _resolve_path(result_data, result_path)
                if value is not None and isinstance(target_param, str):
                    feedback_params[target_param] = value

            if not feedback_params:
                continue

            feedback_params["skip_hooks"] = True

            # Add source entity IDs for writeback context
            if "todo_id" in source:
                feedback_params["todo_id"] = source["todo_id"]
            if "project_name" in source:
                feedback_params["project_name"] = source["project_name"]

            if trigger_url:
                try:
                    fb_result = await post_hook(
                        hook_id=f"{hook.id}-feedback",
                        url=trigger_url,
                        target_tool=hook.feedback_tool,
                        params=feedback_params,
                    )
                    feedback_results.append(
                        {
                            "hook_id": hook.id,
                            "feedback_tool": hook.feedback_tool,
                            "ok": fb_result.ok,
                            "error": fb_result.error,
                        }
                    )
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
                        errors.append(
                            {
                                "hook_id": f"{hook.id}-feedback",
                                "error": err_msg,
                                "target_tool": hook.feedback_tool,
                            }
                        )
                except Exception as exc:
                    err_msg = f"feedback writeback exception for {hook.id}: {exc}"
                    feedback_results.append(
                        {
                            "hook_id": hook.id,
                            "feedback_tool": hook.feedback_tool,
                            "ok": False,
                            "error": str(exc),
                        }
                    )
                    storage.log_failure(
                        hook_id=f"{hook.id}-feedback",
                        trigger_tool=hook.trigger_tool,
                        target_tool=hook.feedback_tool,
                        server=hook.server,
                        error=err_msg,
                        source_result=source_result,
                    )
                    errors.append(
                        {
                            "hook_id": f"{hook.id}-feedback",
                            "error": err_msg,
                            "target_tool": hook.feedback_tool,
                        }
                    )

    # Phase 1.6: Cascade dispatch for blocking hooks
    cascade_errors: list[str] = []
    for hook in blocking_hooks:
        raw = results_by_id.get(hook.id)
        if raw is None:
            continue
        # Cascade check: block dispatch if the next level would reach max_depth.
        # Invariant: depths 0…max_depth-1 execute; depth max_depth never runs.
        # Example with max_depth=3: depth 2 cascade blocked (2+1=3 >= 3 → skip).
        if depth + 1 >= max_depth:
            continue
        try:
            nested_source = json.loads(raw) if isinstance(raw, str) else raw
            if not isinstance(nested_source, dict):
                continue
            nested = await _fire_hooks_internal(
                hook.target_tool,
                nested_source,
                depth + 1,
                raw,
                max_depth,
                base_config,
            )
            # Collect nested errors with chain path prefix
            nested_errors = nested.get("errors", [])
            if isinstance(nested_errors, list):
                for err in nested_errors:
                    chain = f"[{trigger_tool} \u2192 {hook.id} \u2192 {hook.target_tool}]"
                    err_msg = str(err.get("error", str(err))) if isinstance(err, dict) else str(err)
                    cascade_errors.append(f"{chain} {err_msg}")
            # Propagate deeper cascade errors
            nested_cascade = nested.get("cascade_errors", [])
            if isinstance(nested_cascade, list):
                cascade_errors.extend(str(e) for e in nested_cascade)
        except Exception:
            logger.debug("Cascade failure (non-fatal)", exc_info=True)

    # Schedule non-blocking hooks (fire-and-forget)
    non_blocking_dispatched = 0
    non_blocking_results: list[dict[str, JsonValue]] = []
    for hook in non_blocking_hooks:
        task = asyncio.create_task(_launch_nonblocking(hook, source, source_result))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        non_blocking_dispatched += 1
        non_blocking_results.append(
            {"hook_id": hook.id, "target_tool": hook.target_tool, "status": "dispatched"}
        )

    # Phase 2: Fire verification hooks with enriched source_result
    verification_results: list[dict[str, JsonValue]] = []
    if verification_matched:
        # Build hook_results dict from Phase 1 blocking results
        hook_results: dict[str, JsonValue] = dict(results_by_id.items())

        enriched: dict[str, JsonValue] = {**source, "hook_results": hook_results}
        verification_results = await _fire_verification(
            verification_matched,
            enriched,
            trigger_tool,
            source_result,
            base_config,
        )

    target_tool_by_id = {hook.id: hook.target_tool for hook in blocking_hooks}
    errors_jv: JsonValue = cast("JsonValue", errors)
    summary: dict[str, JsonValue] = {
        "hooks_fired": fired,
        "skipped": len(skipped_hooks),
        "skipped_hooks": cast("JsonValue", skipped_hooks),
        "errors": errors_jv,
        "results": cast(
            "JsonValue",
            [
                {"hook_id": k, "result": v, "target_tool": target_tool_by_id.get(k)}
                for k, v in results_by_id.items()
            ]
            + non_blocking_results,
        ),
        "depth": depth,
        "max_depth": max_depth,
        "non_blocking_dispatched": non_blocking_dispatched,
        "top_level": depth == 0,
    }
    if verification_results:
        summary["verification"] = cast("JsonValue", verification_results)
    if feedback_results:
        summary["feedback"] = cast("JsonValue", feedback_results)
    if cascade_errors:
        summary["cascade_errors"] = cast("JsonValue", cascade_errors)
    return summary


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
        return json.dumps(
            {
                "hooks_fired": 0,
                "skipped": 0,
                "errors": [],
                "depth_limited": True,
                "depth": depth,
                "max_depth": max_depth,
                "message": msg,
            }
        )

    # Parse source_result
    try:
        source: dict[str, JsonValue] = json.loads(source_result)
        if not isinstance(source, dict):
            return "Error: source_result must be a JSON object, got " + type(source).__name__
    except json.JSONDecodeError as e:
        return f"Error: source_result is not valid JSON: {e}"

    # Build merged config for condition evaluation
    base_config = _load_proj_config()
    if source:
        # Inject todo-level fields
        todo_fields = {
            k: v
            for k, v in source.items()
            if k
            in (
                "todoist_task_id",
                "trello_card_id",
                "trello_checklist_id",
                "trello_checklist_item_id",
                "jira_issue_key",
                "parent_todoist_task_id",
            )
        }
        if todo_fields:
            todo_section = base_config.get("todo")
            if not isinstance(todo_section, dict):
                todo_section = {}
                base_config["todo"] = todo_section
            todo_section.update(todo_fields)
        # Inject project-level fields
        project_fields = {
            k: v
            for k, v in source.items()
            if k
            in (
                "todoist_project_id",
                "trello_card_id",
                "trello_checklist_id",
            )
        }
        if project_fields:
            project_section = base_config.get("project")
            if not isinstance(project_section, dict):
                project_section = {}
                base_config["project"] = project_section
            project_section.update(project_fields)

    summary = await _fire_hooks_internal(
        trigger_tool,
        source,
        depth,
        source_result,
        max_depth,
        base_config,
    )
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
            "Returns JSON summary: {hooks_fired, skipped, errors, "
            "non_blocking_dispatched, depth, max_depth}."
        )
    )
    async def router_fire_tool(
        trigger_tool: str,
        source_result: str = "{}",
        depth: int = 0,
    ) -> str:
        return await hooks_fire(
            trigger_tool=trigger_tool,
            source_result=source_result,
            depth=depth,
        )
