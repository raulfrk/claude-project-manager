"""Monkey-patch FastMCP's mcp.tool() to dispatch hooks after every tool execution."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine, Sequence
from typing import TYPE_CHECKING, ParamSpec, Protocol, TypeVar, runtime_checkable

import httpx

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("hook_dispatch")

_MAX_RESULT_BYTES = 100 * 1024  # 100 KB

JsonValue = str | int | float | bool | None | dict[str, "JsonValue"] | list["JsonValue"]
ToolResult = str | dict[str, JsonValue] | list[JsonValue] | None

P = ParamSpec("P")
R = TypeVar("R")


@runtime_checkable
class _ContentBlock(Protocol):
    """Duck type for MCP ContentBlock objects that have a .text attribute."""

    @property
    def text(self) -> str: ...


_RawToolOutput = ToolResult | Sequence[_ContentBlock]


def _serialize_result(result: _RawToolOutput) -> str:
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
        items = list(result)
        if items and isinstance(items[0], _ContentBlock):
            texts = [item.text for item in items if isinstance(item, _ContentBlock)]
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
    result: _RawToolOutput,
    hooks_port: int = 19100,
) -> dict[str, JsonValue] | None:
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
                data: dict[str, JsonValue] = resp.json()
                return data
            except Exception:
                logger.warning("Hook dispatch for %s: malformed JSON response", tool_name)
                return {"_error": "malformed response", "hooks_fired": 0, "errors": [], "results": []}
    except (httpx.ConnectError, httpx.TimeoutException):
        logger.warning("Hook dispatch failed for %s: hooks server unreachable", tool_name)
        return {"_error": "hooks server unreachable", "hooks_fired": 0, "errors": [], "results": []}
    except Exception:
        logger.warning("Hook dispatch failed for %s", tool_name, exc_info=True)
        return None


def _build_hooks_field(fire_response: dict[str, JsonValue] | None, tool_name: str) -> dict[str, JsonValue] | None:
    """Map a hooks_fire_tool response to the _hooks injection format.

    Returns None when injection should be skipped (zero hooks, nested dispatch).
    Returns a hooks_field dict when injection should proceed.
    """
    if fire_response is None:
        return None

    has_error = "_error" in fire_response
    hooks_fired = fire_response.get("hooks_fired", 0)
    raw_errors = fire_response.get("errors", [])
    errors_list: list[dict[str, JsonValue]] = [
        e for e in (raw_errors if isinstance(raw_errors, list) else []) if isinstance(e, dict)
    ]

    # Skip injection for nested dispatches (fire.py sets top_level=True only at depth=0)
    if not has_error and not fire_response.get("top_level"):
        return None

    # Skip injection when zero hooks fired and no errors (common case — clean exit)
    if not has_error and hooks_fired == 0 and not errors_list:
        return None

    # Build chain from results (ok) + errors
    raw_results_val = fire_response.get("results", [])
    raw_results: list[dict[str, JsonValue]] = [
        r for r in (raw_results_val if isinstance(raw_results_val, list) else [])
        if isinstance(r, dict)
    ]
    chain: list[JsonValue] = []
    for r in raw_results:
        entry: dict[str, JsonValue] = {"hook_id": str(r.get("hook_id")), "target_tool": str(r.get("target_tool")) if r.get("target_tool") else None, "status": "ok", "error": None}
        chain.append(entry)
    for e in errors_list:
        entry = {"hook_id": str(e.get("hook_id")), "target_tool": str(e.get("target_tool")) if e.get("target_tool") else None, "status": "error", "error": str(e.get("error")) if e.get("error") else None}
        chain.append(entry)

    error_strings: list[JsonValue] = []
    if has_error:
        error_strings = [str(fire_response["_error"])]
    else:
        error_strings = [
            str(e.get("error", str(e))) for e in errors_list
        ]

    # Merge cascade errors from nested hook dispatch
    raw_cascade = fire_response.get("cascade_errors", [])
    cascade_errors: list[str] = [
        str(ce) for ce in (raw_cascade if isinstance(raw_cascade, list) else [])
    ]
    for ce in cascade_errors:
        error_strings.append(ce)

    return {
        "_claude_instructions": (
            "Hook chain completed. Check _hooks.errors and chain entries with "
            "status=error for failures. Explain any errors to the user."
        ),
        "hooks_fired": hooks_fired,
        "chain": chain,
        "errors": error_strings,
    }


def _inject_hooks(original: _RawToolOutput, hooks_field: dict[str, JsonValue]) -> str | dict[str, JsonValue]:
    """Inject a _hooks field into a tool result.

    Handles all result shapes: JSON object string, JSON non-object, non-JSON string,
    None, dict, ContentBlock list. Truncates chain if post-injection size > 100KB.
    """

    def _build_with_hooks(base: dict[str, JsonValue]) -> str:
        base["_hooks"] = hooks_field
        result_str = json.dumps(base, ensure_ascii=True)
        if len(result_str.encode()) > _MAX_RESULT_BYTES:
            existing_errors = hooks_field.get("errors")
            truncated_field: dict[str, JsonValue] = {
                **hooks_field,
                "chain": [],
                "errors": (existing_errors if isinstance(existing_errors, list) else []) + ["chain truncated: result too large"],
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

    if isinstance(original, (list, tuple)):
        items = list(original)
        if items and isinstance(items[0], _ContentBlock):
            texts = [item.text for item in items if isinstance(item, _ContentBlock)]
            text: str = texts[0] if len(texts) == 1 else json.dumps(texts)
            return json.dumps({"result": text, "_hooks": hooks_field})

    return json.dumps({"result": str(original), "_hooks": hooks_field})


_GenericToolFn = Callable[..., ToolResult]
_ToolDecorator = Callable[[_GenericToolFn], _GenericToolFn]


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
        name: str | _GenericToolFn | None = None,
        title: str | None = None,
        description: str | None = None,
        **kwargs: JsonValue,
    ) -> _GenericToolFn | _ToolDecorator:
        # Handle both @mcp.tool and @mcp.tool() and @mcp.tool(name="x")
        # If called with a callable as first arg, it's @mcp.tool without parens
        if callable(name):
            fn = name
            tool_name = fn.__name__
            if tool_name in excluded:
                return original_tool()(fn)
            wrapped = _wrap_tool_fn(fn, tool_name, hooks_port)
            return original_tool()(wrapped)

        # @mcp.tool() or @mcp.tool(name="custom", ...) — returns a decorator
        custom_name = name

        decorator: _ToolDecorator = original_tool(
            name=name if isinstance(name, str) else None,
            title=title,
            description=description,
            **kwargs,  # type: ignore[arg-type]
        )

        def wrapper(fn: _GenericToolFn) -> _GenericToolFn:
            tool_name = str(custom_name) if custom_name else fn.__name__
            if tool_name in excluded:
                return decorator(fn)
            wrapped = _wrap_tool_fn(fn, tool_name, hooks_port)
            return decorator(wrapped)  # type: ignore[arg-type]

        return wrapper

    mcp.tool = patched_tool  # type: ignore[assignment,method-assign]


def _wrap_tool_fn(
    fn: Callable[P, R],
    tool_name: str,
    hooks_port: int,
) -> Callable[P, Coroutine[None, None, R | str | dict[str, JsonValue]]]:
    """Wrap a tool function to dispatch hooks after successful execution.

    Both sync and async tools get an async wrapper. FastMCP's call_fn_with_arg_validation
    checks is_async on the wrapper (not the original), so async wrappers work for both.
    The key: we must NOT use functools.wraps for sync->async conversion, because wraps
    copies __wrapped__ which FastMCP may inspect. Instead we manually copy __name__,
    __doc__, and __module__, and set __signature__ from the original.

    Hook chain results are injected into the tool result as a ``_hooks`` field when
    hooks fired at the top level (depth=0) and hooks_fired > 0 or errors occurred.
    """
    import inspect

    if asyncio.iscoroutinefunction(fn):

        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R | str | dict[str, JsonValue]:
            result: R = await fn(*args, **kwargs)
            fire_response = await _dispatch_hook(tool_name, result, hooks_port)  # type: ignore[arg-type]
            hooks_field = _build_hooks_field(fire_response, tool_name)
            if hooks_field is not None:
                return _inject_hooks(result, hooks_field)  # type: ignore[arg-type]
            return result

        async_wrapper.__name__ = fn.__name__
        async_wrapper.__doc__ = fn.__doc__
        async_wrapper.__module__ = fn.__module__
        setattr(async_wrapper, "__signature__", inspect.signature(fn))  # noqa: B010
        setattr(async_wrapper, "__wrapped__", fn)  # noqa: B010
        async_wrapper.__annotations__ = getattr(fn, "__annotations__", {})

        return async_wrapper

    # Sync tool: wrap as async so dispatch can be awaited.
    # Copy signature from original fn so FastMCP argument validation works.
    async def sync_to_async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R | str | dict[str, JsonValue]:
        result: R = fn(*args, **kwargs)
        fire_response = await _dispatch_hook(tool_name, result, hooks_port)  # type: ignore[arg-type]
        hooks_field = _build_hooks_field(fire_response, tool_name)
        if hooks_field is not None:
            return _inject_hooks(result, hooks_field)  # type: ignore[arg-type]
        return result

    sync_to_async_wrapper.__name__ = fn.__name__
    sync_to_async_wrapper.__doc__ = fn.__doc__
    sync_to_async_wrapper.__module__ = fn.__module__
    setattr(sync_to_async_wrapper, "__signature__", inspect.signature(fn))  # noqa: B010
    sync_to_async_wrapper.__annotations__ = getattr(fn, "__annotations__", {})

    return sync_to_async_wrapper
