"""Integration tests for hook dispatch — end-to-end with real FastMCP instances.

Verifies that enable_hook_dispatch() correctly wires into FastMCP's tool
registration and that dispatched payloads reach the hooks server endpoint.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import httpx
import pytest
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from hook_dispatch import enable_hook_dispatch

# ── Helpers ───────────────────────────────────────────────────────────────────


def _capturing_transport(captured: list[dict]) -> httpx.MockTransport:
    """Mock transport that captures POST payloads and returns 200."""

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        return httpx.Response(200, json={"ok": True, "result": None})

    return httpx.MockTransport(handler)


def _slow_transport(captured: list[dict], delay: float) -> httpx.MockTransport:
    """Transport that delays before responding (simulates blocking hook)."""

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured.append(body)
        await asyncio.sleep(delay)
        return httpx.Response(200, json={"ok": True, "result": "hook_done"})

    return httpx.MockTransport(handler)


def _error_transport() -> httpx.MockTransport:
    """Transport that raises ConnectError (simulates hooks server down)."""

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    return httpx.MockTransport(handler)


_RealAsyncClient = httpx.AsyncClient


def _patch_client_factory(transport: httpx.MockTransport):
    """Patch httpx.AsyncClient constructor to create fresh clients with the given transport.

    Each call to AsyncClient() returns a new instance (avoids 'cannot reopen' errors).
    Uses saved reference to real AsyncClient to avoid recursive mock calls.
    """

    def factory(**kwargs):
        return _RealAsyncClient(transport=transport)

    return patch("hook_dispatch.dispatch.httpx.AsyncClient", side_effect=factory)


# ── Test: tool call dispatches correct payload to hooks server ────────────────


@pytest.mark.anyio
async def test_e2e_tool_dispatches_correct_payload():
    """A tool registered on a real FastMCP dispatches to the hooks server with correct format."""
    captured: list[dict] = []

    mcp = FastMCP("test_e2e")
    enable_hook_dispatch(mcp, hooks_port=19999)

    @mcp.tool(description="Test tool")
    async def greet(name: str) -> str:
        return f"hello {name}"

    with _patch_client_factory(_capturing_transport(captured)):
        result = await mcp._tool_manager.call_tool("greet", {"name": "world"})

    assert result is not None
    assert len(captured) == 1
    payload = captured[0]
    assert payload["tool"] == "router_fire_tool"
    assert payload["params"]["trigger_tool"] == "greet"
    assert payload["params"]["depth"] == 0
    source = json.loads(payload["params"]["source_result"])
    assert "hello world" in str(source)


# ── Test: tool with custom name dispatches with registered name ──────────────


@pytest.mark.anyio
async def test_e2e_custom_name_dispatched():
    """@mcp.tool(name="custom") dispatches with the registered name, not function name."""
    captured: list[dict] = []

    mcp = FastMCP("test_custom")
    enable_hook_dispatch(mcp, hooks_port=19999)

    @mcp.tool(name="my_custom_tool", description="Custom named tool")
    async def internal_fn(x: int) -> int:
        return x * 2

    with _patch_client_factory(_capturing_transport(captured)):
        await mcp._tool_manager.call_tool("my_custom_tool", {"x": 5})

    assert len(captured) == 1
    assert captured[0]["params"]["trigger_tool"] == "my_custom_tool"


# ── Test: blocking — tool waits for hook response before returning ───────────


@pytest.mark.anyio
async def test_e2e_blocking_hook_awaited():
    """The dispatcher awaits the hooks server response (simulated with delay)."""
    captured: list[dict] = []

    mcp = FastMCP("test_blocking")
    enable_hook_dispatch(mcp, hooks_port=19999)

    @mcp.tool(description="Blocking test")
    async def blocking_tool() -> str:
        return "done"

    with _patch_client_factory(_slow_transport(captured, delay=0.1)):
        result = await mcp._tool_manager.call_tool("blocking_tool", {})

    # Dispatch was awaited — captured list has the payload
    assert len(captured) == 1
    assert result is not None


# ── Test: hooks server down — tool returns normally ──────────────────────────


@pytest.mark.anyio
async def test_e2e_hooks_server_down_returns_normally(caplog):
    """When hooks server is unreachable, tool returns its result with a warning."""
    import logging

    caplog.set_level(logging.WARNING, logger="hook_dispatch")

    mcp = FastMCP("test_down")
    enable_hook_dispatch(mcp, hooks_port=19999)

    @mcp.tool(description="Resilient tool")
    async def resilient() -> str:
        return "still works"

    with _patch_client_factory(_error_transport()):
        result = await mcp._tool_manager.call_tool("resilient", {})

    assert result is not None
    assert "unreachable" in caplog.text.lower() or "refused" in caplog.text.lower()


# ── Test: no hooks registered — dispatch still fires (hooks server decides) ──


@pytest.mark.anyio
async def test_e2e_dispatch_fires_even_without_registered_hooks():
    """Dispatch always POSTs to hooks server — the hooks server decides if hooks match."""
    captured: list[dict] = []

    mcp = FastMCP("test_noop")
    enable_hook_dispatch(mcp, hooks_port=19999)

    @mcp.tool(description="No-op dispatch")
    async def noop_tool() -> str:
        return "noop"

    with _patch_client_factory(_capturing_transport(captured)):
        result = await mcp._tool_manager.call_tool("noop_tool", {})

    assert len(captured) == 1
    assert result is not None


# ── Test: excluded tool skips dispatch entirely ──────────────────────────────


@pytest.mark.anyio
async def test_e2e_excluded_tool_no_dispatch():
    """Tools in the exclude list skip dispatch entirely."""
    captured: list[dict] = []

    mcp = FastMCP("test_exclude")
    enable_hook_dispatch(mcp, hooks_port=19999, exclude=["meta_tool"])

    @mcp.tool(name="meta_tool", description="Excluded tool")
    async def meta_fn() -> str:
        return "meta"

    @mcp.tool(description="Normal tool")
    async def normal_tool() -> str:
        return "normal"

    with _patch_client_factory(_capturing_transport(captured)):
        await mcp._tool_manager.call_tool("meta_tool", {})
        await mcp._tool_manager.call_tool("normal_tool", {})

    # Only normal_tool dispatched
    assert len(captured) == 1
    assert captured[0]["params"]["trigger_tool"] == "normal_tool"


# ── Test: sync tool function works through FastMCP ───────────────────────────


@pytest.mark.anyio
async def test_e2e_sync_tool_dispatches():
    """Sync tools are wrapped as async and dispatch correctly via call_tool."""
    captured: list[dict] = []

    mcp = FastMCP("test_sync")
    enable_hook_dispatch(mcp, hooks_port=19999)

    @mcp.tool(description="Sync tool")
    def sync_add(a: int, b: int) -> int:
        return a + b

    with _patch_client_factory(_capturing_transport(captured)):
        await mcp._tool_manager.call_tool("sync_add", {"a": 3, "b": 4})

    assert len(captured) == 1
    source = json.loads(captured[0]["params"]["source_result"])
    assert source == 7 or "7" in str(source)


# ── Test: tool exception propagates without dispatch ─────────────────────────


@pytest.mark.anyio
async def test_e2e_exception_no_dispatch():
    """Tool exceptions propagate to caller without dispatching hooks."""
    captured: list[dict] = []

    mcp = FastMCP("test_exc")
    enable_hook_dispatch(mcp, hooks_port=19999)

    @mcp.tool(description="Failing tool")
    async def boom() -> str:
        raise RuntimeError("kaboom")

    with _patch_client_factory(_capturing_transport(captured)), pytest.raises(ToolError):
        await mcp._tool_manager.call_tool("boom", {})

    assert len(captured) == 0


# ── Test: multiple tools on same instance all dispatch ───────────────────────


@pytest.mark.anyio
async def test_e2e_multiple_tools_all_dispatch():
    """Multiple tools registered on the same FastMCP instance all dispatch correctly."""
    captured: list[dict] = []

    mcp = FastMCP("test_multi")
    enable_hook_dispatch(mcp, hooks_port=19999)

    @mcp.tool(description="Tool A")
    async def tool_a() -> str:
        return "a"

    @mcp.tool(description="Tool B")
    async def tool_b() -> str:
        return "b"

    @mcp.tool(name="tool_c", description="Tool C")
    async def internal_c() -> str:
        return "c"

    with _patch_client_factory(_capturing_transport(captured)):
        await mcp._tool_manager.call_tool("tool_a", {})
        await mcp._tool_manager.call_tool("tool_b", {})
        await mcp._tool_manager.call_tool("tool_c", {})

    assert len(captured) == 3
    trigger_names = [c["params"]["trigger_tool"] for c in captured]
    assert trigger_names == ["tool_a", "tool_b", "tool_c"]


# ── Test: dict result serialized correctly in dispatch ───────────────────────


@pytest.mark.anyio
async def test_e2e_dict_result_serialized():
    """Dict results are serialized to JSON string in the dispatch payload."""
    captured: list[dict] = []

    mcp = FastMCP("test_dict")
    enable_hook_dispatch(mcp, hooks_port=19999)

    @mcp.tool(description="Dict tool")
    async def dict_tool() -> dict:
        return {"status": "ok", "count": 42}

    with _patch_client_factory(_capturing_transport(captured)):
        await mcp._tool_manager.call_tool("dict_tool", {})

    assert len(captured) == 1
    source = json.loads(captured[0]["params"]["source_result"])
    assert source == {"status": "ok", "count": 42}
