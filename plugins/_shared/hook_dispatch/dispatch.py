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


async def _dispatch_hook(
    tool_name: str,
    result: Any,
    hooks_url: str,
) -> None:
    """POST hook dispatch to the hooks server. Swallows connection/timeout errors."""
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
        transport = httpx.AsyncHTTPTransport(proxy=None)
        async with httpx.AsyncClient(timeout=30.0, transport=transport) as client:
            await client.post(hooks_url, json=payload)
    except (httpx.ConnectError, httpx.TimeoutException):
        logger.warning("Hook dispatch failed for %s: hooks server unreachable", tool_name)
    except Exception:
        logger.warning("Hook dispatch failed for %s", tool_name, exc_info=True)


def enable_hook_dispatch(
    mcp: FastMCP,
    hooks_port: int = 19100,
    exclude: set[str] | list[str] | None = None,
) -> None:
    """Patch mcp.tool() so all subsequent registrations dispatch to the hooks server.

    Args:
        mcp: The FastMCP instance to patch.
        hooks_port: Port of the hooks server (default 19100).
        exclude: Tool names to skip dispatch for.
    """
    hooks_url = f"http://127.0.0.1:{hooks_port}/hook"
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
            wrapped = _wrap_tool_fn(fn, tool_name, hooks_url)
            return original_tool(wrapped)

        # @mcp.tool() or @mcp.tool(name="custom", ...) — returns a decorator
        custom_name = kwargs.get("name")

        decorator = original_tool(*args, **kwargs)

        def wrapper(fn: Any) -> Any:
            tool_name = custom_name or fn.__name__
            if tool_name in excluded:
                return decorator(fn)
            wrapped = _wrap_tool_fn(fn, tool_name, hooks_url)
            return decorator(wrapped)

        return wrapper

    mcp.tool = patched_tool  # type: ignore[method-assign]


def _wrap_tool_fn(fn: Any, tool_name: str, hooks_url: str) -> Any:
    """Wrap a tool function to dispatch hooks after successful execution.

    Both sync and async tools get an async wrapper. FastMCP's call_fn_with_arg_validation
    checks is_async on the wrapper (not the original), so async wrappers work for both.
    The key: we must NOT use functools.wraps for sync→async conversion, because wraps
    copies __wrapped__ which FastMCP may inspect. Instead we manually copy __name__,
    __doc__, and __module__, and set __signature__ from the original.
    """
    import inspect

    if asyncio.iscoroutinefunction(fn):

        @functools.wraps(fn)
        async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await fn(*args, **kwargs)
            await _dispatch_hook(tool_name, result, hooks_url)
            return result

        return async_wrapper

    # Sync tool: wrap as async so dispatch can be awaited.
    # Copy signature from original fn so FastMCP argument validation works.
    async def sync_to_async_wrapper(*args: Any, **kwargs: Any) -> Any:
        result = fn(*args, **kwargs)
        await _dispatch_hook(tool_name, result, hooks_url)
        return result

    sync_to_async_wrapper.__name__ = fn.__name__
    sync_to_async_wrapper.__doc__ = fn.__doc__
    sync_to_async_wrapper.__module__ = fn.__module__
    sync_to_async_wrapper.__signature__ = inspect.signature(fn)
    sync_to_async_wrapper.__annotations__ = getattr(fn, "__annotations__", {})

    return sync_to_async_wrapper
