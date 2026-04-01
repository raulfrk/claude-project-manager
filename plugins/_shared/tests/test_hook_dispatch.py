"""Tests for hook_dispatch — the enable_hook_dispatch() monkey-patch."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from hook_dispatch.dispatch import (
    _build_hooks_field,
    _dispatch_hook,
    _inject_hooks,
    _resolve_hooks_transport,
    _serialize_result,
    enable_hook_dispatch,
)


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

    with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None) as mock_dispatch:
        result = await mock_mcp._registered_tools["my_sync_tool"](42)

    assert result == "result-42"
    mock_dispatch.assert_awaited_once()
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

    with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None) as mock_dispatch:
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

    # Server unreachable now injects _hooks with error rather than returning raw result
    result_data = json.loads(result)
    assert result_data["result"] == "ok"
    assert any("unreachable" in e for e in result_data["_hooks"]["errors"])
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

    # Server timeout now injects _hooks with error rather than returning raw result
    result_data = json.loads(result)
    assert result_data["result"] == "done"
    assert any("unreachable" in e for e in result_data["_hooks"]["errors"])


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

    with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None) as mock_dispatch:
        result = await mock_mcp._registered_tools["custom_name"]()

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

    with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None) as mock_dispatch:
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

    with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None) as mock_dispatch:
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
async def test_dispatch_payload_format_unix(mock_mcp):
    """Default Unix socket dispatch sends correct payload."""
    enable_hook_dispatch(mock_mcp, hooks_port=19100)

    @mock_mcp.tool()
    async def payload_tool() -> dict:
        return {"status": "ok"}

    with patch("hook_dispatch.dispatch.httpx.AsyncClient") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hooks_fired": 0, "errors": [], "results": [], "top_level": False}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await mock_mcp._registered_tools["payload_tool"]()

    mock_client.post.assert_awaited_once()
    url, kwargs = mock_client.post.call_args[0][0], mock_client.post.call_args[1]
    assert url == "http://localhost/hook"
    payload = kwargs["json"]
    assert payload["tool"] == "hooks_fire_tool"
    assert payload["params"]["trigger_tool"] == "payload_tool"
    assert payload["params"]["depth"] == 0
    assert json.loads(payload["params"]["source_result"]) == {"status": "ok"}


@pytest.mark.anyio
async def test_dispatch_payload_format_tcp(mock_mcp, monkeypatch):
    """TCP fallback dispatch sends to http://127.0.0.1:{port}/hook."""
    monkeypatch.setenv("HOOK_TRANSPORT", "tcp")
    enable_hook_dispatch(mock_mcp, hooks_port=19100)

    @mock_mcp.tool()
    async def tcp_tool() -> dict:
        return {"val": 1}

    with patch("hook_dispatch.dispatch.httpx.AsyncClient") as mock_client_cls:
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hooks_fired": 0, "errors": [], "results": [], "top_level": False}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await mock_mcp._registered_tools["tcp_tool"]()

    url = mock_client.post.call_args[0][0]
    assert url == "http://127.0.0.1:19100/hook"


# ── _resolve_hooks_transport registry tests ─────────────────────────────────


class TestResolveHooksTransport:
    """Tests for registry-aware transport resolution."""

    def test_reads_registry_file_in_unix_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unix mode reads ~/.claude/sockets/hooks for the socket path."""
        monkeypatch.delenv("HOOK_TRANSPORT", raising=False)
        sockets_dir = tmp_path / ".claude" / "sockets"
        sockets_dir.mkdir(parents=True)
        registry_file = sockets_dir / "hooks"
        registry_file.write_text("/tmp/claude-hooks-hooks-99999.sock")

        with patch("pathlib.Path.home", return_value=tmp_path):
            url, transport = _resolve_hooks_transport(19100)

        assert url == "http://localhost/hook"
        assert isinstance(transport, httpx.AsyncHTTPTransport)
        # Verify the transport was configured with the registry socket path
        assert transport._pool._uds == "/tmp/claude-hooks-hooks-99999.sock"

    def test_fallback_when_registry_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back to legacy socket path when registry file is absent."""
        monkeypatch.delenv("HOOK_TRANSPORT", raising=False)
        # tmp_path has no .claude/sockets/hooks — triggers FileNotFoundError

        with patch("pathlib.Path.home", return_value=tmp_path):
            url, transport = _resolve_hooks_transport(19100)

        assert url == "http://localhost/hook"
        assert isinstance(transport, httpx.AsyncHTTPTransport)
        assert transport._pool._uds == "/tmp/claude-hooks-hooks.sock"

    def test_fallback_when_registry_empty(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back to legacy socket path when registry file is empty."""
        monkeypatch.delenv("HOOK_TRANSPORT", raising=False)
        sockets_dir = tmp_path / ".claude" / "sockets"
        sockets_dir.mkdir(parents=True)
        registry_file = sockets_dir / "hooks"
        registry_file.write_text("   \n")

        with patch("pathlib.Path.home", return_value=tmp_path):
            url, transport = _resolve_hooks_transport(19100)

        assert url == "http://localhost/hook"
        assert transport._pool._uds == "/tmp/claude-hooks-hooks.sock"

    def test_tcp_mode_uses_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TCP mode returns http URL with the given port, no UDS."""
        monkeypatch.setenv("HOOK_TRANSPORT", "tcp")

        url, transport = _resolve_hooks_transport(19100)

        assert url == "http://127.0.0.1:19100/hook"
        assert isinstance(transport, httpx.AsyncHTTPTransport)

    def test_tcp_mode_different_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TCP mode respects the hooks_port argument."""
        monkeypatch.setenv("HOOK_TRANSPORT", "tcp")

        url, transport = _resolve_hooks_transport(19200)

        assert url == "http://127.0.0.1:19200/hook"


# ── _dispatch_hook return value ──────────────────────────────────────────────


class TestDispatchHookReturn:
    @pytest.mark.anyio
    async def test_returns_dict_on_success(self):
        """_dispatch_hook returns parsed JSON dict from hooks server."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"hooks_fired": 1, "errors": [], "results": [{"hook_id": "h1", "result": "ok"}], "top_level": True}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("hook_dispatch.dispatch.httpx.AsyncClient", return_value=mock_client):
            result = await _dispatch_hook("my_tool", "result", "http://localhost/hook")

        assert isinstance(result, dict)
        assert result["hooks_fired"] == 1

    @pytest.mark.anyio
    async def test_returns_error_dict_on_connect_error(self):
        """_dispatch_hook returns error dict (not None) on ConnectError."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("hook_dispatch.dispatch.httpx.AsyncClient", return_value=mock_client):
            result = await _dispatch_hook("my_tool", "result", "http://localhost/hook")

        assert result is not None
        assert "_error" in result
        assert "unreachable" in result["_error"]

    @pytest.mark.anyio
    async def test_returns_error_dict_on_malformed_json(self):
        """_dispatch_hook returns error dict when resp.json() raises."""
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("not json")
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("hook_dispatch.dispatch.httpx.AsyncClient", return_value=mock_client):
            result = await _dispatch_hook("my_tool", "result", "http://localhost/hook")

        assert result is not None
        assert "_error" in result
        assert "malformed" in result["_error"]


# ── _build_hooks_field ───────────────────────────────────────────────────────


class TestBuildHooksField:
    def test_returns_none_when_fire_response_is_none(self):
        assert _build_hooks_field(None, "tool") is None

    def test_returns_none_when_not_top_level(self):
        response = {"hooks_fired": 2, "errors": [], "results": [{"hook_id": "h1", "result": "x"}], "top_level": False}
        assert _build_hooks_field(response, "tool") is None

    def test_returns_none_when_zero_hooks_no_errors(self):
        response = {"hooks_fired": 0, "errors": [], "results": [], "top_level": True}
        assert _build_hooks_field(response, "tool") is None

    def test_returns_field_when_hooks_fired(self):
        response = {"hooks_fired": 1, "errors": [], "results": [{"hook_id": "h1", "result": "ok"}], "top_level": True}
        field = _build_hooks_field(response, "tool")
        assert field is not None
        assert field["hooks_fired"] == 1
        assert len(field["chain"]) == 1
        assert field["chain"][0]["status"] == "ok"
        assert "_claude_instructions" in field

    def test_returns_field_on_error_case(self):
        """Error dict (_error key) always triggers injection regardless of top_level."""
        response = {"_error": "hooks server unreachable", "hooks_fired": 0, "errors": [], "results": []}
        field = _build_hooks_field(response, "tool")
        assert field is not None
        assert "hooks server unreachable" in field["errors"]

    def test_chain_includes_error_entries(self):
        response = {
            "hooks_fired": 2,
            "errors": [{"hook_id": "h2", "error": "timeout"}],
            "results": [{"hook_id": "h1", "result": "ok"}],
            "top_level": True,
        }
        field = _build_hooks_field(response, "tool")
        assert field is not None
        assert len(field["chain"]) == 2
        ok_entry = next(e for e in field["chain"] if e["hook_id"] == "h1")
        err_entry = next(e for e in field["chain"] if e["hook_id"] == "h2")
        assert ok_entry["status"] == "ok"
        assert err_entry["status"] == "error"
        assert err_entry["error"] == "timeout"

    def test_defensive_missing_keys(self):
        """Missing keys in response use fallback values."""
        response = {"top_level": True, "hooks_fired": 1}  # missing errors, results
        field = _build_hooks_field(response, "tool")
        assert field is not None
        assert field["chain"] == []
        assert field["errors"] == []


# ── _inject_hooks ────────────────────────────────────────────────────────────


class TestInjectHooks:
    def _hooks_field(self):
        return {"_claude_instructions": "test", "hooks_fired": 1, "chain": [], "errors": []}

    def test_injects_into_json_object_string(self):
        original = json.dumps({"status": "ok", "data": 42})
        result = _inject_hooks(original, self._hooks_field())
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert "_hooks" in parsed

    def test_wraps_json_non_object(self):
        original = json.dumps([1, 2, 3])
        result = _inject_hooks(original, self._hooks_field())
        parsed = json.loads(result)
        assert parsed["result"] == [1, 2, 3]
        assert "_hooks" in parsed

    def test_wraps_non_json_string(self):
        result = _inject_hooks("plain string result", self._hooks_field())
        parsed = json.loads(result)
        assert parsed["result"] == "plain string result"
        assert "_hooks" in parsed

    def test_wraps_none(self):
        result = _inject_hooks(None, self._hooks_field())
        parsed = json.loads(result)
        assert parsed["result"] is None
        assert "_hooks" in parsed

    def test_injects_into_dict(self):
        original = {"key": "val"}
        result = _inject_hooks(original, self._hooks_field())
        assert isinstance(result, dict)
        assert result["key"] == "val"
        assert "_hooks" in result

    def test_truncates_chain_when_result_too_large(self):
        """Large result causes chain to be truncated to preserve 100KB limit."""
        large_hooks = {
            "_claude_instructions": "test",
            "hooks_fired": 1,
            "chain": [{"hook_id": f"h{i}", "status": "ok", "error": None} for i in range(5000)],
            "errors": [],
        }
        original = json.dumps({"data": "x" * 80_000})  # 80KB base
        result = _inject_hooks(original, large_hooks)
        parsed = json.loads(result)
        # Chain should be truncated
        assert parsed["_hooks"]["chain"] == []
        assert any("truncated" in e for e in parsed["_hooks"]["errors"])


# ── Full wrap integration ────────────────────────────────────────────────────


class TestWrapInjectsHooks:
    @pytest.mark.anyio
    async def test_injects_when_hooks_fired(self, mock_mcp):
        """Tool result gets _hooks field when hooks fired at top level."""
        enable_hook_dispatch(mock_mcp)

        @mock_mcp.tool()
        async def hooked_tool() -> str:
            return json.dumps({"status": "done"})

        fire_response = {
            "hooks_fired": 1,
            "errors": [],
            "results": [{"hook_id": "h1", "result": "synced"}],
            "top_level": True,
        }
        with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=fire_response):
            result = await mock_mcp._registered_tools["hooked_tool"]()

        parsed = json.loads(result)
        assert parsed["status"] == "done"
        assert "_hooks" in parsed
        assert parsed["_hooks"]["hooks_fired"] == 1
        assert parsed["_hooks"]["chain"][0]["hook_id"] == "h1"

    @pytest.mark.anyio
    async def test_skips_injection_when_zero_hooks(self, mock_mcp):
        """Tool result is returned unchanged when no hooks fired."""
        enable_hook_dispatch(mock_mcp)

        @mock_mcp.tool()
        async def unhooked_tool() -> str:
            return json.dumps({"status": "clean"})

        fire_response = {"hooks_fired": 0, "errors": [], "results": [], "top_level": True}
        with patch("hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=fire_response):
            result = await mock_mcp._registered_tools["unhooked_tool"]()

        parsed = json.loads(result)
        assert parsed == {"status": "clean"}
        assert "_hooks" not in parsed
