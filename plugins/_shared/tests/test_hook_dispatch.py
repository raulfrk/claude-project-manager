"""Tests for hook_dispatch — the enable_hook_dispatch() monkey-patch."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from hook_dispatch.dispatch import _serialize_result, enable_hook_dispatch


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_mcp():
    """Create a mock FastMCP instance with a working tool() method."""
    mcp = MagicMock()
    registered_tools: dict[str, object] = {}

    def fake_tool(*args, **kwargs):
        """Mimic FastMCP.tool() — supports @mcp.tool, @mcp.tool(), @mcp.tool(name=...)."""
        if args and callable(args[0]) and not kwargs:
            # @mcp.tool without parens
            fn = args[0]
            registered_tools[fn.__name__] = fn
            return fn

        # @mcp.tool() or @mcp.tool(name="custom")
        name = kwargs.get("name")

        def decorator(fn):
            tool_name = name or fn.__name__
            registered_tools[tool_name] = fn
            return fn

        return decorator

    mcp.tool = fake_tool
    mcp._registered_tools = registered_tools
    return mcp


# ── Sync tool wrapping ───────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_wraps_sync_function(mock_mcp):
    enable_hook_dispatch(mock_mcp)

    @mock_mcp.tool()
    def my_sync_tool(x: int) -> str:
        return f"result-{x}"

    with patch("hook_dispatch.dispatch._dispatch_hook_background") as mock_dispatch:
        result = mock_mcp._registered_tools["my_sync_tool"](42)

    assert result == "result-42"
    mock_dispatch.assert_called_once()
    call_args = mock_dispatch.call_args
    assert call_args[0][0] == "my_sync_tool"
    assert call_args[0][1] == "result-42"


# ── Async tool wrapping ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_wraps_async_function(mock_mcp):
    enable_hook_dispatch(mock_mcp)

    @mock_mcp.tool()
    async def my_async_tool(x: int) -> str:
        return f"async-{x}"

    with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock) as mock_dispatch:
        result = await mock_mcp._registered_tools["my_async_tool"](10)

    assert result == "async-10"
    mock_dispatch.assert_awaited_once()
    assert mock_dispatch.call_args[0][0] == "my_async_tool"


# ── Hooks server unreachable ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_hooks_unreachable_returns_result(mock_mcp, caplog):
    enable_hook_dispatch(mock_mcp, hooks_port=19199)

    @mock_mcp.tool()
    async def resilient_tool() -> str:
        return "ok"

    with patch("hook_dispatch.dispatch.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await mock_mcp._registered_tools["resilient_tool"]()

    assert result == "ok"
    assert "unreachable" in caplog.text.lower() or "refused" in caplog.text.lower()


@pytest.mark.anyio
async def test_hooks_timeout_returns_result(mock_mcp, caplog):
    enable_hook_dispatch(mock_mcp, hooks_port=19199)

    @mock_mcp.tool()
    async def timeout_tool() -> str:
        return "done"

    with patch("hook_dispatch.dispatch.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.TimeoutException("timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await mock_mcp._registered_tools["timeout_tool"]()

    assert result == "done"


# ── Tool exception propagation ───────────────────────────────────────────────


@pytest.mark.anyio
async def test_tool_exception_propagates_no_dispatch(mock_mcp):
    enable_hook_dispatch(mock_mcp)

    @mock_mcp.tool()
    async def failing_tool() -> str:
        raise ValueError("boom")

    with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock) as mock_dispatch:
        with pytest.raises(ValueError, match="boom"):
            await mock_mcp._registered_tools["failing_tool"]()

    mock_dispatch.assert_not_awaited()


# ── Large result truncation ──────────────────────────────────────────────────


def test_large_result_truncated(caplog):
    big_string = "x" * 200_000
    result = _serialize_result(big_string)
    assert result.endswith("...[truncated]")
    assert "truncating" in caplog.text.lower()


def test_small_result_not_truncated():
    result = _serialize_result("small")
    assert result == json.dumps("small")
    assert "truncated" not in result


# ── Patching mcp.tool ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_enable_patches_mcp_tool(mock_mcp):
    original = mock_mcp.tool
    enable_hook_dispatch(mock_mcp)
    assert mock_mcp.tool is not original


# ── Custom tool name ─────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_custom_tool_name_dispatched(mock_mcp):
    enable_hook_dispatch(mock_mcp)

    @mock_mcp.tool(name="custom_name")
    async def internal_fn() -> str:
        return "custom"

    with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock) as mock_dispatch:
        result = await mock_mcp._registered_tools["custom_name"](  )

    assert result == "custom"
    assert mock_dispatch.call_args[0][0] == "custom_name"


# ── Excluded tool names ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_excluded_tool_skips_dispatch(mock_mcp):
    enable_hook_dispatch(mock_mcp, exclude={"skip_me"})

    @mock_mcp.tool(name="skip_me")
    async def skip_fn() -> str:
        return "skipped"

    with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock) as mock_dispatch:
        result = await mock_mcp._registered_tools["skip_me"]()

    assert result == "skipped"
    mock_dispatch.assert_not_awaited()


@pytest.mark.anyio
async def test_non_excluded_tool_dispatches(mock_mcp):
    enable_hook_dispatch(mock_mcp, exclude={"other_tool"})

    @mock_mcp.tool(name="allowed_tool")
    async def allowed_fn() -> str:
        return "allowed"

    with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock) as mock_dispatch:
        result = await mock_mcp._registered_tools["allowed_tool"]()

    assert result == "allowed"
    mock_dispatch.assert_awaited_once()


# ── @mcp.tool without parens ─────────────────────────────────────────────────


@pytest.mark.anyio
async def test_tool_without_parens(mock_mcp):
    enable_hook_dispatch(mock_mcp)

    @mock_mcp.tool
    async def bare_tool() -> str:
        return "bare"

    with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock) as mock_dispatch:
        result = await mock_mcp._registered_tools["bare_tool"]()

    assert result == "bare"
    mock_dispatch.assert_awaited_once()
    assert mock_dispatch.call_args[0][0] == "bare_tool"


# ── Serialization edge cases ─────────────────────────────────────────────────


def test_serialize_dict():
    assert _serialize_result({"key": "val"}) == json.dumps({"key": "val"})


def test_serialize_list():
    assert _serialize_result([1, 2, 3]) == json.dumps([1, 2, 3])


def test_serialize_none():
    assert _serialize_result(None) == "null"


def test_serialize_int():
    assert _serialize_result(42) == "42"


def test_serialize_bool():
    assert _serialize_result(True) == "true"


def test_serialize_content_block_single():
    block = MagicMock()
    block.text = "hello"
    result = _serialize_result([block])
    assert result == json.dumps("hello")


def test_serialize_content_block_multiple():
    block1 = MagicMock()
    block1.text = "a"
    block2 = MagicMock()
    block2.text = "b"
    result = _serialize_result([block1, block2])
    assert result == json.dumps(["a", "b"])


# ── Dispatch payload format ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_dispatch_payload_format(mock_mcp):
    enable_hook_dispatch(mock_mcp, hooks_port=19100)

    @mock_mcp.tool()
    async def payload_tool() -> dict:
        return {"status": "ok"}

    with patch("hook_dispatch.dispatch.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await mock_mcp._registered_tools["payload_tool"]()

    mock_client.post.assert_awaited_once()
    url, kwargs = mock_client.post.call_args[0][0], mock_client.post.call_args[1]
    assert url == "http://127.0.0.1:19100/hook"
    payload = kwargs["json"]
    assert payload["tool"] == "hooks_fire_tool"
    assert payload["params"]["trigger_tool"] == "payload_tool"
    assert payload["params"]["depth"] == 0
    assert json.loads(payload["params"]["source_result"]) == {"status": "ok"}
