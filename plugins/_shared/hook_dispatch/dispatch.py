"""Monkey-patch FastMCP's mcp.tool() to dispatch hooks after every tool execution."""

from __future__ import annotations

import asyncio
import functools
import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("hook_dispatch")

_MAX_RESULT_BYTES = 100 * 1024  # 100 KB


def _serialize_result(result: Any) -> str:
    """Serialize a tool result to a JSON string, truncating at 100KB."""
    if result is None:
        serialized = "null"
    elif isinstance(result, str):
        # If the string is already valid JSON object/array, pass through as-is
        try:
            parsed = json.loads(result)
            if isinstance(parsed, (dict, list)):
                serialized = result
            else:
                serialized = json.dumps(result)
        except (json.JSONDecodeError, ValueError):
            serialized = json.dumps(result)
    elif isinstance(result, (dict, int, float, bool)):
        serialized = json.dumps(result)
    elif isinstance(result, (list, tuple)):
        # Check for ContentBlock sequences (objects with .text attribute)
        items = list(result)
        if items and hasattr(items[0], "text"):
            texts = [item.text for item in items if hasattr(item, "text")]
            serialized = json.dumps(texts[0] if len(texts) == 1 else texts)
        else:
            serialized = json.dumps(items)
    else:
        serialized = json.dumps(str(result))

    encoded = serialized.encode("utf-8")
    if len(encoded) > _MAX_RESULT_BYTES:
        logger.warning(
            "Hook dispatch result exceeds 100KB (%d bytes), truncating",
            len(encoded),
        )
        serialized = encoded[:_MAX_RESULT_BYTES].decode("utf-8", errors="ignore") + "...[truncated]"

    return serialized


def _resolve_hooks_transport(hooks_port: int) -> tuple[str, httpx.AsyncBaseTransport | None]:
    """Resolve the hooks server transport URL.

    In Unix mode (default): reads ~/.claude/sockets/hooks to get the current
    session's socket path. Falls back to legacy path if registry missing.
    In TCP mode (HOOK_TRANSPORT=tcp): returns http://127.0.0.1:{hooks_port}/hook
    """
    import os
    from pathlib import Path

    transport_mode = os.environ.get("HOOK_TRANSPORT", "unix").lower()
    if transport_mode == "tcp":
        return f"http://127.0.0.1:{hooks_port}/hook", httpx.AsyncHTTPTransport(proxy=None)

    # Unix mode: read registry file for current session's socket path
    registry_file = Path.home() / ".claude" / "sockets" / "hooks"
    sock_path = "/tmp/claude-hooks-hooks.sock"  # legacy fallback
    try:
        path = registry_file.read_text().strip()
        if path:
            sock_path = path
    except (FileNotFoundError, OSError):
        logger.warning(
            "hooks socket registry not found at %s, falling back to legacy path",
            registry_file,
        )

    return "http://localhost/hook", httpx.AsyncHTTPTransport(uds=sock_path)


async def _dispatch_hook(
    tool_name: str,
    result: Any,
    hooks_port: int = 19100,
) -> dict | None:
    """POST hook dispatch to the hooks server. Returns the parsed response dict.

    Resolves the hooks server URL from the registry on every call so that a
    stale cached path (from a server restart) never causes permanent failures.

    Returns None if the hooks server is unreachable or an unrecoverable error occurs.
    Returns a dict with '_error' key if the response is malformed.
    """
    hooks_url, hooks_transport = _resolve_hooks_transport(hooks_port)
    serialized = _serialize_result(result)
    payload = {
        "tool": "hooks_fire_tool",
        "params": {
            "trigger_tool": tool_name,
            "source_result": serialized,
            "depth": 0,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=30.0, transport=hooks_transport) as client:
            resp = await client.post(hooks_url, json=payload)
            try:
                return resp.json()
            except Exception:
                logger.warning("Hook dispatch for %s: malformed JSON response", tool_name)
                return {"_error": "malformed response", "hooks_fired": 0, "errors": [], "results": []}
    except (httpx.ConnectError, httpx.TimeoutException):
        logger.warning("Hook dispatch failed for %s: hooks server unreachable", tool_name)
        return {"_error": "hooks server unreachable", "hooks_fired": 0, "errors": [], "results": []}
    except Exception:
        logger.warning("Hook dispatch failed for %s", tool_name, exc_info=True)
        return None


def _build_hooks_field(fire_response: dict | None, tool_name: str) -> dict | None:
    """Map a hooks_fire_tool response to the _hooks injection format.

    Returns None when injection should be skipped (zero hooks, nested dispatch).
    Returns a hooks_field dict when injection should proceed.
    """
    if fire_response is None:
        return None

    has_error = "_error" in fire_response
    hooks_fired = fire_response.get("hooks_fired", 0)
    errors_list = fire_response.get("errors", [])

    # Skip injection for nested dispatches (fire.py sets top_level=True only at depth=0)
    if not has_error and not fire_response.get("top_level"):
        return None

    # Skip injection when zero hooks fired and no errors (common case — clean exit)
    if not has_error and hooks_fired == 0 and not errors_list:
        return None

    # Build chain from results (ok) + errors
    chain: list[dict[str, Any]] = [
        {"hook_id": r["hook_id"], "target_tool": r.get("target_tool"), "status": "ok", "error": None}
        for r in fire_response.get("results", [])
    ] + [
        {"hook_id": e["hook_id"], "target_tool": e.get("target_tool"), "status": "error", "error": e.get("error")}
        for e in errors_list
        if isinstance(e, dict)
    ]

    error_strings: list[str] = []
    if has_error:
        error_strings = [str(fire_response["_error"])]
    else:
        error_strings = [
            e.get("error", str(e)) for e in errors_list if isinstance(e, dict)
        ]

    return {
        "_claude_instructions": (
            "Hook chain completed. Check _hooks.errors and chain entries with "
            "status=error for failures. Explain any errors to the user."
        ),
        "hooks_fired": hooks_fired,
        "chain": chain,
        "errors": error_strings,
    }


def _inject_hooks(original: Any, hooks_field: dict) -> Any:
    """Inject a _hooks field into a tool result.

    Handles all result shapes: JSON object string, JSON non-object, non-JSON string,
    None, dict, ContentBlock list. Truncates chain if post-injection size > 100KB.
    """

    def _build_with_hooks(base: dict) -> str:
        base["_hooks"] = hooks_field
        result_str = json.dumps(base, ensure_ascii=True)
        if len(result_str.encode()) > _MAX_RESULT_BYTES:
            truncated_field = {
                **hooks_field,
                "chain": [],
                "errors": hooks_field.get("errors", []) + ["chain truncated: result too large"],
            }
            base["_hooks"] = truncated_field
            result_str = json.dumps(base, ensure_ascii=True)
        return result_str

    if original is None:
        return json.dumps({"result": None, "_hooks": hooks_field})

    if isinstance(original, str):
        try:
            parsed = json.loads(original)
            if isinstance(parsed, dict):
                return _build_with_hooks(parsed)
            else:
                return _build_with_hooks({"result": parsed})
        except (json.JSONDecodeError, ValueError):
            return _build_with_hooks({"result": original})

    if isinstance(original, dict):
        original["_hooks"] = hooks_field
        return original

    items = list(original) if isinstance(original, (list, tuple)) else None
    if items and hasattr(items[0], "text"):
        texts = [item.text for item in items if hasattr(item, "text")]
        text = texts[0] if len(texts) == 1 else json.dumps(texts)
        return json.dumps({"result": text, "_hooks": hooks_field})

    return json.dumps({"result": str(original), "_hooks": hooks_field})


def enable_hook_dispatch(
    mcp: FastMCP,
    hooks_port: int = 19100,
    exclude: set[str] | list[str] | None = None,
) -> None:
    """Patch mcp.tool() so all subsequent registrations dispatch to the hooks server.

    The hooks server URL is resolved lazily on every dispatch call (not at startup),
    so that server restarts and startup ordering races don't cause permanent failures.

    Args:
        mcp: The FastMCP instance to patch.
        hooks_port: Port of the hooks server (default 19100). Only used with HOOK_TRANSPORT=tcp.
        exclude: Tool names to skip dispatch for.
    """
    excluded: set[str] = set(exclude) if exclude else set()
    original_tool = mcp.tool

    def patched_tool(
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        # Handle both @mcp.tool and @mcp.tool() and @mcp.tool(name="x")
        # If called with a callable as first arg, it's @mcp.tool without parens
        if args and callable(args[0]) and not kwargs:
            # @mcp.tool  (no parens)
            fn = args[0]
            tool_name = fn.__name__
            if tool_name in excluded:
                return original_tool(fn)
            wrapped = _wrap_tool_fn(fn, tool_name, hooks_port)
            return original_tool(wrapped)

        # @mcp.tool() or @mcp.tool(name="custom", ...) — returns a decorator
        custom_name = kwargs.get("name")

        decorator = original_tool(*args, **kwargs)

        def wrapper(fn: Any) -> Any:
            tool_name = custom_name or fn.__name__
            if tool_name in excluded:
                return decorator(fn)
            wrapped = _wrap_tool_fn(fn, tool_name, hooks_port)
            return decorator(wrapped)

        return wrapper

    mcp.tool = patched_tool  # type: ignore[method-assign]


def _wrap_tool_fn(
    fn: Any,
    tool_name: str,
    hooks_port: int,
) -> Any:
    """Wrap a tool function to dispatch hooks after successful execution.

    Both sync and async tools get an async wrapper. FastMCP's call_fn_with_arg_validation
    checks is_async on the wrapper (not the original), so async wrappers work for both.
    The key: we must NOT use functools.wraps for sync→async conversion, because wraps
    copies __wrapped__ which FastMCP may inspect. Instead we manually copy __name__,
    __doc__, and __module__, and set __signature__ from the original.

    Hook chain results are injected into the tool result as a ``_hooks`` field when
    hooks fired at the top level (depth=0) and hooks_fired > 0 or errors occurred.
    """
    import inspect

    if asyncio.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await fn(*args, **kwargs)
            fire_response = await _dispatch_hook(tool_name, result, hooks_port)
            hooks_field = _build_hooks_field(fire_response, tool_name)
            if hooks_field is not None:
                return _inject_hooks(result, hooks_field)
            return result

        return async_wrapper

    # Sync tool: wrap as async so dispatch can be awaited.
    # Copy signature from original fn so FastMCP argument validation works.
    async def sync_to_async_wrapper(*args: Any, **kwargs: Any) -> Any:
        result = fn(*args, **kwargs)
        fire_response = await _dispatch_hook(tool_name, result, hooks_port)
        hooks_field = _build_hooks_field(fire_response, tool_name)
        if hooks_field is not None:
            return _inject_hooks(result, hooks_field)
        return result

    sync_to_async_wrapper.__name__ = fn.__name__
    sync_to_async_wrapper.__doc__ = fn.__doc__
    sync_to_async_wrapper.__module__ = fn.__module__
    sync_to_async_wrapper.__signature__ = inspect.signature(fn)
    sync_to_async_wrapper.__annotations__ = getattr(fn, "__annotations__", {})

    return sync_to_async_wrapper
