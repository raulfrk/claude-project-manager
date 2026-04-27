"""Tests for hook_dispatch — the enable_hook_dispatch() monkey-patch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from hook_dispatch.dispatch import (
    _build_hooks_field,
    _dispatch_hook,
    _format_error,
    _inject_dispatch,
    _merge_feedback,
    _resolve_hooks_transport,
    _serialize_result,
    enable_hook_dispatch,
)

if TYPE_CHECKING:
    from collections.abc import Callable

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_mcp():
    """Create a mock FastMCP instance with a working tool() method."""
    mcp = MagicMock()
    registered_tools: dict[str, Callable[..., str | None]] = {}

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

    with patch(
        "hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None
    ) as mock_dispatch:
        result = await mock_mcp._registered_tools["my_sync_tool"](42)

    assert result == "result-42"
    mock_dispatch.assert_awaited_once()
    call_args = mock_dispatch.call_args
    assert call_args[0][0] == "my_sync_tool"
    assert call_args[0][1] == "result-42"
    assert call_args[0][2] == 19100  # hooks_port passed through


# ── Async tool wrapping ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_wraps_async_function(mock_mcp):
    enable_hook_dispatch(mock_mcp)

    @mock_mcp.tool()
    async def my_async_tool(x: int) -> str:
        return f"async-{x}"

    with patch(
        "hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None
    ) as mock_dispatch:
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

    # Bypass the null-transport short-circuit (added for todo 669) so the
    # ConnectError path in _dispatch_hook is exercised. In CI neither
    # ~/.claude/sockets/router nor /tmp sockets exist, so without this patch
    # _resolve_hooks_transport returns (url, None) and dispatch never reaches
    # httpx.AsyncClient.
    with (
        patch(
            "hook_dispatch.dispatch._resolve_hooks_transport",
            return_value=("http://localhost/hook", MagicMock()),
        ),
        patch("hook_dispatch.dispatch.httpx.AsyncClient") as mock_client_cls,
    ):
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


def test_resolve_hooks_transport_glob_fallback_honors_tmpdir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: glob fallback in _resolve_hooks_transport must use the same
    socket_dir() that the bind site uses. Pre-fix, the glob hardcoded "/tmp"
    so on hosts with TMPDIR != /tmp the fallback always returned no candidates
    → dispatch returned (url, None) → "hooks server unreachable" warnings
    whenever the primary registry-file lookup also failed.

    Post-793, both the bind site and the glob fallback resolve through
    hook_transport.socket_path.socket_dir(), so monkeypatching the helper
    affects both.
    """
    # Force socket_dir() onto a non-/tmp path. _resolve_hooks_transport
    # imports socket_dir/socket_glob locally, so the patch applied to the
    # source module is picked up on every call. Bind to a local name to
    # bypass the package __init__.py re-export (which makes the bare attr
    # 'hook_transport.socket_path' resolve to the function, not the module).
    import sys

    sp_module = sys.modules["hook_transport.socket_path"]

    fake_tmpdir = tmp_path / "fake-tmpdir"
    fake_tmpdir.mkdir()
    monkeypatch.setattr(sp_module, "socket_dir", lambda: fake_tmpdir)

    # Create a fake PID-tagged router socket file in the non-/tmp dir.
    sock = fake_tmpdir / "claude-cpm-router-12345.sock"
    sock.touch()

    # Force the registry-file primary lookup to fail (point HOME at a tmp dir
    # with no ~/.claude/sockets/router).
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: tmp_path))

    # Unix mode by default. Disable TCP fallback path.
    monkeypatch.delenv("HOOK_TRANSPORT", raising=False)

    url, transport = _resolve_hooks_transport(hooks_port=0)

    # Glob fallback found the socket → returns httpx.AsyncHTTPTransport(uds=...)
    # rather than (url, None). Pre-fix, transport would be None because the
    # glob looked in /tmp and the socket is in fake_tmpdir.
    assert transport is not None, (
        "Glob fallback failed to find socket in non-/tmp socket_dir() — "
        "_resolve_hooks_transport may still be hardcoding /tmp"
    )
    assert url == "http://localhost/hook"


@pytest.mark.anyio
async def test_hooks_timeout_returns_result(mock_mcp, caplog):
    enable_hook_dispatch(mock_mcp, hooks_port=19199)

    @mock_mcp.tool()
    async def timeout_tool() -> str:
        return "done"

    # Bypass the null-transport short-circuit so the TimeoutException path runs.
    with (
        patch(
            "hook_dispatch.dispatch._resolve_hooks_transport",
            return_value=("http://localhost/hook", MagicMock()),
        ),
        patch("hook_dispatch.dispatch.httpx.AsyncClient") as mock_client_cls,
    ):
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

    with (
        patch(
            "hook_dispatch.dispatch._dispatch_hook",
            new_callable=AsyncMock,
        ) as mock_dispatch,
        pytest.raises(ValueError, match="boom"),
    ):
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

    with patch(
        "hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None
    ) as mock_dispatch:
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

    with patch(
        "hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None
    ) as mock_dispatch:
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

    with patch(
        "hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None
    ) as mock_dispatch:
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


def test_serialize_float():
    assert _serialize_result(3.14) == "3.14"


def test_serialize_json_string_passthrough():
    """A string that is already valid JSON dict passes through as-is."""
    json_str = '{"key": "val"}'
    result = _serialize_result(json_str)
    assert result == json_str


def test_serialize_json_array_string_passthrough():
    """A string that is already a valid JSON array passes through as-is."""
    json_str = "[1, 2, 3]"
    result = _serialize_result(json_str)
    assert result == json_str


def test_serialize_plain_string_gets_quoted():
    """A plain string (not JSON) gets JSON-encoded (quoted)."""
    result = _serialize_result("hello world")
    assert result == '"hello world"'


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


def test_serialize_unknown_type_falls_back_to_str():
    """Unknown types are converted via str() and JSON-encoded."""

    class Custom:
        def __str__(self):
            return "custom-repr"

    result = _serialize_result(Custom())  # type: ignore[arg-type]
    assert result == json.dumps("custom-repr")


# ── Dispatch payload format ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_dispatch_payload_format_unix(mock_mcp, tmp_path, monkeypatch):
    """Default Unix socket dispatch sends correct payload."""
    monkeypatch.delenv("HOOK_TRANSPORT", raising=False)
    sockets_dir = tmp_path / ".claude" / "sockets"
    sockets_dir.mkdir(parents=True)
    (sockets_dir / "router").write_text("/tmp/claude-cpm-router-99999.sock")

    enable_hook_dispatch(mock_mcp, hooks_port=19100)

    @mock_mcp.tool()
    async def payload_tool() -> dict:
        return {"status": "ok"}

    # _resolve_hooks_transport checks the sock file exists (it doesn't in CI);
    # patch it to return a non-None transport so dispatch reaches httpx.
    with (
        patch("pathlib.Path.home", return_value=tmp_path),
        patch(
            "hook_dispatch.dispatch._resolve_hooks_transport",
            return_value=("http://localhost/hook", MagicMock()),
        ),
        patch("hook_dispatch.dispatch.httpx.AsyncClient") as mock_client_cls,
    ):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hooks_fired": 0,
            "errors": [],
            "results": [],
            "top_level": False,
        }
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
    assert payload["tool"] == "router_fire_tool"
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
        mock_resp.json.return_value = {
            "hooks_fired": 0,
            "errors": [],
            "results": [],
            "top_level": False,
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        await mock_mcp._registered_tools["tcp_tool"]()

    url = mock_client.post.call_args[0][0]
    assert url == "http://127.0.0.1:19100/hook"


@pytest.mark.anyio
async def test_lazy_resolution_reads_fresh_registry(mock_mcp, tmp_path, monkeypatch):
    """Transport is re-resolved on every dispatch, so registry changes take effect immediately."""
    monkeypatch.delenv("HOOK_TRANSPORT", raising=False)
    sockets_dir = tmp_path / ".claude" / "sockets"
    sockets_dir.mkdir(parents=True)
    registry_file = sockets_dir / "router"
    registry_file.write_text("/tmp/claude-cpm-router-11111.sock")

    enable_hook_dispatch(mock_mcp, hooks_port=19100)

    @mock_mcp.tool()
    async def refreshable_tool() -> str:
        return "ok"

    call_count = 0

    def fake_resolve(port):
        nonlocal call_count
        call_count += 1
        path = registry_file.read_text().strip()
        import httpx as _httpx

        return "http://localhost/hook", _httpx.AsyncHTTPTransport(uds=path)

    with (
        patch(
            "hook_dispatch.dispatch._resolve_hooks_transport",
            side_effect=fake_resolve,
        ),
        patch(
            "hook_dispatch.dispatch.httpx.AsyncClient",
        ) as mock_cls,
    ):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hooks_fired": 0,
            "errors": [],
            "results": [],
            "top_level": False,
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        # First call: registry points to 11111
        await mock_mcp._registered_tools["refreshable_tool"]()
        assert call_count == 1

        # Simulate hooks server restart — registry now points to 22222
        registry_file.write_text("/tmp/claude-cpm-router-22222.sock")

        # Second call: must re-resolve, picking up the new path
        await mock_mcp._registered_tools["refreshable_tool"]()
        assert call_count == 2


# ── _resolve_hooks_transport registry tests ─────────────────────────────────


class TestResolveHooksTransport:
    """Tests for registry-aware transport resolution."""

    def test_reads_registry_file_in_unix_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unix mode reads ~/.claude/sockets/router for the socket path."""
        monkeypatch.delenv("HOOK_TRANSPORT", raising=False)
        sockets_dir = tmp_path / ".claude" / "sockets"
        sockets_dir.mkdir(parents=True)
        registry_file = sockets_dir / "router"
        registry_file.write_text("/tmp/claude-cpm-router-99999.sock")

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("pathlib.Path.exists", return_value=True),
        ):
            url, transport = _resolve_hooks_transport(19100)

        assert url == "http://localhost/hook"
        assert isinstance(transport, httpx.AsyncHTTPTransport)
        # Verify the transport was configured with the registry socket path
        assert transport._pool._uds == "/tmp/claude-cpm-router-99999.sock"

    def test_fallback_when_registry_missing_uses_glob(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back to glob for PID-tagged sockets when registry is absent."""
        monkeypatch.delenv("HOOK_TRANSPORT", raising=False)

        mock_socks = [
            Path("/tmp/claude-cpm-router-111.sock"),
            Path("/tmp/claude-cpm-router-222.sock"),
        ]
        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("pathlib.Path.glob", return_value=mock_socks),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_mtime = 1000
            url, transport = _resolve_hooks_transport(19100)

        assert url == "http://localhost/hook"
        assert isinstance(transport, httpx.AsyncHTTPTransport)
        assert "claude-cpm-router-" in transport._pool._uds

    def test_fallback_when_registry_empty_uses_glob(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falls back to glob when registry file is empty."""
        monkeypatch.delenv("HOOK_TRANSPORT", raising=False)
        sockets_dir = tmp_path / ".claude" / "sockets"
        sockets_dir.mkdir(parents=True)
        (sockets_dir / "router").write_text("   \n")

        mock_socks = [Path("/tmp/claude-cpm-router-333.sock")]
        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("pathlib.Path.glob", return_value=mock_socks),
            patch("pathlib.Path.stat") as mock_stat,
        ):
            mock_stat.return_value.st_mtime = 1000
            url, transport = _resolve_hooks_transport(19100)

        assert url == "http://localhost/hook"
        assert "claude-cpm-router-" in transport._pool._uds

    def test_no_fallback_when_no_glob_matches(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Returns None transport when registry missing AND no glob matches.

        Per D512.3 (HARD CUT): the legacy compat fallback path was removed.
        Dispatch should fail rather than silently target a stale path.
        """
        monkeypatch.delenv("HOOK_TRANSPORT", raising=False)

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("pathlib.Path.glob", return_value=[]),
        ):
            url, transport = _resolve_hooks_transport(19100)

        assert url == "http://localhost/hook"
        assert transport is None

    def test_tcp_mode_uses_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TCP mode returns http URL with the given port, no UDS."""
        monkeypatch.setenv("HOOK_TRANSPORT", "tcp")

        url, transport = _resolve_hooks_transport(19100)

        assert url == "http://127.0.0.1:19100/hook"
        assert isinstance(transport, httpx.AsyncHTTPTransport)

    def test_tcp_mode_different_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """TCP mode respects the hooks_port argument."""
        monkeypatch.setenv("HOOK_TRANSPORT", "tcp")

        url, _transport = _resolve_hooks_transport(19200)

        assert url == "http://127.0.0.1:19200/hook"


# ── _dispatch_hook return value ──────────────────────────────────────────────


class TestDispatchHookReturn:
    @pytest.mark.anyio
    async def test_returns_dict_on_success(self):
        """_dispatch_hook returns parsed JSON dict from hooks server."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "hooks_fired": 1,
            "errors": [],
            "results": [{"hook_id": "h1", "result": "ok"}],
            "top_level": True,
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "hook_dispatch.dispatch._resolve_hooks_transport",
                return_value=("http://localhost/hook", MagicMock()),
            ),
            patch("hook_dispatch.dispatch.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await _dispatch_hook("my_tool", "result", 19100)

        assert isinstance(result, dict)
        assert result["hooks_fired"] == 1

    @pytest.mark.anyio
    async def test_returns_error_dict_on_connect_error(self):
        """_dispatch_hook returns error dict (not None) on ConnectError."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = httpx.ConnectError("refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "hook_dispatch.dispatch._resolve_hooks_transport",
                return_value=("http://localhost/hook", MagicMock()),
            ),
            patch("hook_dispatch.dispatch.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await _dispatch_hook("my_tool", "result", 19100)

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

        with (
            patch(
                "hook_dispatch.dispatch._resolve_hooks_transport",
                return_value=("http://localhost/hook", MagicMock()),
            ),
            patch("hook_dispatch.dispatch.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await _dispatch_hook("my_tool", "result", 19100)

        assert result is not None
        assert "_error" in result
        assert "malformed" in result["_error"]

    @pytest.mark.anyio
    async def test_returns_none_on_unexpected_exception(self):
        """_dispatch_hook returns None on unexpected exceptions (not Connect/Timeout)."""
        mock_client = AsyncMock()
        mock_client.post.side_effect = RuntimeError("unexpected internal error")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "hook_dispatch.dispatch._resolve_hooks_transport",
                return_value=("http://localhost/hook", MagicMock()),
            ),
            patch("hook_dispatch.dispatch.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await _dispatch_hook("my_tool", "result", 19100)

        assert result is None

    @pytest.mark.anyio
    async def test_unwraps_http_envelope_with_string_result(self):
        """_dispatch_hook unwraps {"ok": true, "result": "<JSON string>"} envelope."""
        inner = json.dumps(
            {
                "hooks_fired": 2,
                "top_level": True,
                "errors": [],
                "results": [{"hook_id": "h1"}],
            }
        )
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": inner}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "hook_dispatch.dispatch._resolve_hooks_transport",
                return_value=("http://localhost/hook", MagicMock()),
            ),
            patch("hook_dispatch.dispatch.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await _dispatch_hook("my_tool", "result", 19100)

        assert isinstance(result, dict)
        assert result["hooks_fired"] == 2
        assert result["top_level"] is True

    @pytest.mark.anyio
    async def test_unwraps_http_envelope_with_dict_result(self):
        """_dispatch_hook unwraps {"ok": true, "result": {dict}} envelope."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "ok": True,
            "result": {
                "hooks_fired": 1,
                "top_level": True,
                "errors": [],
                "results": [],
            },
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "hook_dispatch.dispatch._resolve_hooks_transport",
                return_value=("http://localhost/hook", MagicMock()),
            ),
            patch("hook_dispatch.dispatch.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await _dispatch_hook("my_tool", "result", 19100)

        assert result["hooks_fired"] == 1
        assert result["top_level"] is True

    @pytest.mark.anyio
    async def test_unwrap_falls_through_on_non_json_string_result(self):
        """Non-JSON string in result field returns outer envelope as-is."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": True, "result": "plain text not json"}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "hook_dispatch.dispatch._resolve_hooks_transport",
                return_value=("http://localhost/hook", MagicMock()),
            ),
            patch("hook_dispatch.dispatch.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await _dispatch_hook("my_tool", "result", 19100)

        # Falls through to return outer envelope
        assert result["ok"] is True
        assert result["result"] == "plain text not json"

    @pytest.mark.anyio
    async def test_unwrap_falls_through_on_no_result_key(self):
        """Response without 'result' key is returned as-is (e.g. error responses)."""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"ok": False, "error": "something broke"}
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch(
                "hook_dispatch.dispatch._resolve_hooks_transport",
                return_value=("http://localhost/hook", MagicMock()),
            ),
            patch("hook_dispatch.dispatch.httpx.AsyncClient", return_value=mock_client),
        ):
            result = await _dispatch_hook("my_tool", "result", 19100)

        assert result["ok"] is False
        assert result["error"] == "something broke"


class TestResolveHooksTransportStaleRegistry:
    """Tests for registry pointing to non-existent socket (sandbox PID mismatch)."""

    def test_stale_registry_falls_back_to_glob(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Registry points to non-existent socket -> glob fallback finds real socket."""
        monkeypatch.delenv("HOOK_TRANSPORT", raising=False)
        sockets_dir = tmp_path / ".claude" / "sockets"
        sockets_dir.mkdir(parents=True)
        # Registry points to sandbox PID socket that doesn't exist on host
        (sockets_dir / "router").write_text("/tmp/claude-cpm-router-10.sock")

        mock_socks = [Path("/tmp/claude-cpm-router-4097643.sock")]
        orig_exists = Path.exists

        def fake_exists(p: Path) -> bool:
            if str(p) == "/tmp/claude-cpm-router-10.sock":
                return False
            return orig_exists(p)

        fake_stat = MagicMock()
        fake_stat.st_mtime = 1000

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch(
                "pathlib.Path.exists",
                autospec=True,
                side_effect=fake_exists,
            ),
            patch("pathlib.Path.glob", return_value=mock_socks),
            patch(
                "pathlib.Path.stat",
                autospec=True,
                return_value=fake_stat,
            ),
        ):
            _url, transport = _resolve_hooks_transport(19100)

        assert transport._pool._uds == "/tmp/claude-cpm-router-4097643.sock"

    def test_valid_registry_used_when_socket_exists(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Registry points to existing socket -> used directly, no glob needed."""
        monkeypatch.delenv("HOOK_TRANSPORT", raising=False)
        sockets_dir = tmp_path / ".claude" / "sockets"
        sockets_dir.mkdir(parents=True)
        (sockets_dir / "router").write_text("/tmp/claude-cpm-router-99999.sock")

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("pathlib.Path.exists", return_value=True),
        ):
            _url, transport = _resolve_hooks_transport(19100)

        assert transport._pool._uds == "/tmp/claude-cpm-router-99999.sock"

    def test_glob_picks_newest_socket(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When multiple sockets exist, glob fallback picks the newest by mtime."""
        monkeypatch.delenv("HOOK_TRANSPORT", raising=False)

        mock_socks = [
            Path("/tmp/claude-cpm-router-111.sock"),
            Path("/tmp/claude-cpm-router-222.sock"),
            Path("/tmp/claude-cpm-router-333.sock"),
        ]
        mtimes = {
            "/tmp/claude-cpm-router-111.sock": 1000,
            "/tmp/claude-cpm-router-222.sock": 2000,
            "/tmp/claude-cpm-router-333.sock": 1500,
        }

        with (
            patch("pathlib.Path.home", return_value=tmp_path),
            patch("pathlib.Path.glob", return_value=mock_socks),
            patch(
                "pathlib.Path.stat",
                autospec=True,
                side_effect=lambda p: type("FakeStat", (), {"st_mtime": mtimes[str(p)]})(),
            ),
        ):
            _url, transport = _resolve_hooks_transport(19100)

        # 222 has highest mtime
        assert transport._pool._uds == "/tmp/claude-cpm-router-222.sock"


# ── _build_hooks_field ───────────────────────────────────────────────────────


class TestBuildHooksField:
    def test_returns_none_when_fire_response_is_none(self):
        assert _build_hooks_field(None, "tool") is None

    def test_returns_none_when_not_top_level(self):
        response = {
            "hooks_fired": 2,
            "errors": [],
            "results": [{"hook_id": "h1", "result": "x"}],
            "top_level": False,
        }
        assert _build_hooks_field(response, "tool") is None

    def test_returns_none_when_zero_hooks_no_errors(self):
        response = {"hooks_fired": 0, "errors": [], "results": [], "top_level": True}
        assert _build_hooks_field(response, "tool") is None

    def test_returns_field_when_hooks_fired(self):
        response = {
            "hooks_fired": 1,
            "errors": [],
            "results": [{"hook_id": "h1", "result": "ok"}],
            "top_level": True,
        }
        field = _build_hooks_field(response, "tool")
        assert field is not None
        assert field["hooks_fired"] == 1
        assert len(field["chain"]) == 1
        assert field["chain"][0]["status"] == "ok"
        assert "_claude_instructions" in field

    def test_returns_field_on_error_case(self):
        """Error dict (_error key) always triggers injection regardless of top_level."""
        response = {
            "_error": "hooks server unreachable",
            "hooks_fired": 0,
            "errors": [],
            "results": [],
        }
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
        assert "timeout" in err_entry["error"]
        assert "Hook h2:" in err_entry["error"]

    def test_defensive_missing_keys(self):
        """Missing keys in response use fallback values."""
        response = {"top_level": True, "hooks_fired": 1}  # missing errors, results
        field = _build_hooks_field(response, "tool")
        assert field is not None
        assert field["chain"] == []
        assert field["errors"] == []

    def test_cascade_errors_merged_into_errors(self):
        """cascade_errors from fire response are merged into _hooks.errors."""
        response = {
            "hooks_fired": 1,
            "errors": [{"hook_id": "h1", "error": "direct fail"}],
            "results": [],
            "top_level": True,
            "cascade_errors": [
                "[trigger_a \u2192 hook-a \u2192 target_b] target_c failed",
                "[trigger_a \u2192 hook-a \u2192 target_b"
                " \u2192 hook-b \u2192 target_c] deeper error",
            ],
        }
        field = _build_hooks_field(response, "tool")
        assert field is not None
        assert len(field["errors"]) == 3
        assert "direct fail" in field["errors"][0]
        assert "Hook h1:" in field["errors"][0]
        assert "target_c failed" in field["errors"][1]
        assert "deeper error" in field["errors"][2]

    def test_returns_field_when_skipped_hooks_only(self):
        """When hooks_fired=0 but skipped_hooks is non-empty, still inject _hooks."""
        response = {
            "hooks_fired": 0,
            "errors": [],
            "results": [],
            "top_level": True,
            "skipped_hooks": [
                {"hook_id": "h1", "reason": "condition sync.todoist.enabled evaluated false"},
                {"hook_id": "h2", "reason": "condition sandbox_integration evaluated false"},
            ],
        }
        field = _build_hooks_field(response, "tool")
        assert field is not None
        assert field["hooks_fired"] == 0
        assert len(field["chain"]) == 2
        assert field["chain"][0]["hook_id"] == "h1"
        assert field["chain"][0]["status"] == "skipped"
        assert "todoist" in field["chain"][0]["reason"]
        assert field["chain"][1]["hook_id"] == "h2"
        assert field["chain"][1]["status"] == "skipped"
        assert field["errors"] == []

    def test_skipped_hooks_with_no_reason_gets_default(self):
        """Skipped hook without a reason field gets a default reason string."""
        response = {
            "hooks_fired": 0,
            "errors": [],
            "results": [],
            "top_level": True,
            "skipped_hooks": [{"hook_id": "h1"}],
        }
        field = _build_hooks_field(response, "tool")
        assert field is not None
        assert field["chain"][0]["reason"] == "condition evaluated false"

    def test_skipped_hooks_mixed_with_fired(self):
        """Skipped hooks appear in chain alongside fired hooks."""
        response = {
            "hooks_fired": 1,
            "errors": [],
            "results": [{"hook_id": "h1", "result": "ok"}],
            "top_level": True,
            "skipped_hooks": [{"hook_id": "h2", "reason": "condition was false"}],
        }
        field = _build_hooks_field(response, "tool")
        assert field is not None
        assert field["hooks_fired"] == 1
        assert len(field["chain"]) == 2
        ok_entry = next(e for e in field["chain"] if e["hook_id"] == "h1")
        skip_entry = next(e for e in field["chain"] if e["hook_id"] == "h2")
        assert ok_entry["status"] == "ok"
        assert skip_entry["status"] == "skipped"

    def test_cascade_errors_empty_not_merged(self):
        """Empty cascade_errors list does not add anything to errors."""
        response = {
            "hooks_fired": 1,
            "errors": [],
            "results": [{"hook_id": "h1", "result": "ok"}],
            "top_level": True,
            "cascade_errors": [],
        }
        field = _build_hooks_field(response, "tool")
        assert field is not None
        assert field["errors"] == []


# ── _inject_dispatch ────────────────────────────────────────────────────────────


class TestInjectHooks:
    def _hooks_field(self):
        return {"_claude_instructions": "test", "hooks_fired": 1, "chain": [], "errors": []}

    def test_injects_into_json_object_string(self):
        original = json.dumps({"status": "ok", "data": 42})
        result = _inject_dispatch(original, self._hooks_field())
        parsed = json.loads(result)
        assert parsed["status"] == "ok"
        assert "_hooks" in parsed

    def test_wraps_json_non_object(self):
        original = json.dumps([1, 2, 3])
        result = _inject_dispatch(original, self._hooks_field())
        parsed = json.loads(result)
        assert parsed["result"] == [1, 2, 3]
        assert "_hooks" in parsed

    def test_wraps_non_json_string(self):
        result = _inject_dispatch("plain string result", self._hooks_field())
        parsed = json.loads(result)
        assert parsed["result"] == "plain string result"
        assert "_hooks" in parsed

    def test_wraps_none(self):
        result = _inject_dispatch(None, self._hooks_field())
        parsed = json.loads(result)
        assert parsed["result"] is None
        assert "_hooks" in parsed

    def test_injects_into_dict(self):
        original = {"key": "val"}
        result = _inject_dispatch(original, self._hooks_field())
        assert isinstance(result, dict)
        assert result["key"] == "val"
        assert "_hooks" in result

    def test_wraps_content_block_list(self):
        """ContentBlock list gets serialized and wrapped with _hooks."""
        block = MagicMock()
        block.text = "block text"
        result = _inject_dispatch([block], self._hooks_field())
        parsed = json.loads(result)
        assert parsed["result"] == "block text"
        assert "_hooks" in parsed

    def test_truncates_chain_when_result_too_large(self):
        """Large result causes chain to be truncated to preserve 100KB limit."""
        large_hooks = {
            "_claude_instructions": "test",
            "hooks_fired": 1,
            "chain": [{"hook_id": f"h{i}", "status": "ok", "error": None} for i in range(5000)],
            "errors": [],
        }
        original = json.dumps({"data": "x" * 80_000})  # 80KB base
        result = _inject_dispatch(original, large_hooks)
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
        with patch(
            "hook_dispatch.dispatch._dispatch_hook",
            new_callable=AsyncMock,
            return_value=fire_response,
        ):
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
        with patch(
            "hook_dispatch.dispatch._dispatch_hook",
            new_callable=AsyncMock,
            return_value=fire_response,
        ):
            result = await mock_mcp._registered_tools["unhooked_tool"]()

        parsed = json.loads(result)
        assert parsed == {"status": "clean"}
        assert "_hooks" not in parsed


# ── _format_error ───────────────────────────────────────────────────────────


class TestFormatError:
    def test_401_includes_api_token_fix(self):
        msg = _format_error("HTTP 401 Unauthorized", "hook-001")
        assert "Hook hook-001:" in msg
        assert "401" in msg
        assert "API token" in msg.lower() or "check API token" in msg

    def test_429_includes_rate_limit_fix(self):
        msg = _format_error("HTTP 429 Too Many Requests", "hook-002")
        assert "Hook hook-002:" in msg
        assert "rate" in msg.lower()

    def test_connect_error_includes_server_running_fix(self):
        msg = _format_error("ConnectError: connection refused", "hook-003")
        assert "Hook hook-003:" in msg
        assert "server" in msg.lower() and "running" in msg.lower()

    def test_unknown_error_plain_format(self):
        msg = _format_error("some weird failure", "hook-004")
        assert msg == "Hook hook-004: some weird failure"
        # No "Fix:" suggestion for unknown errors
        assert "Fix:" not in msg

    def test_403_includes_permissions_fix(self):
        msg = _format_error("403 Forbidden", "hook-005")
        assert "Hook hook-005:" in msg
        assert "permission" in msg.lower()

    def test_timeout_includes_health_fix(self):
        msg = _format_error("Request timed out after 30s", "hook-006")
        assert "Hook hook-006:" in msg
        assert "timeout" in msg.lower() or "health" in msg.lower()


# ── _merge_feedback ─────────────────────────────────────────────────────────


class TestMergeFeedback:
    def test_merge_successful_todoist_feedback(self):
        """Successful Todoist feedback merges todoist_task_id into result."""
        original = json.dumps({"status": "ok", "todoist_task_id": None})
        fire_response = {
            "feedback": [{"ok": True, "params": {"todoist_task_id": "t123"}}],
        }
        result = _merge_feedback(original, fire_response)
        parsed = json.loads(result)
        assert parsed["todoist_task_id"] == "t123"
        assert parsed["status"] == "ok"

    def test_merge_successful_trello_feedback(self):
        """Successful Trello feedback merges trello_card_id into result."""
        original = json.dumps({"status": "ok", "trello_card_id": None})
        fire_response = {
            "feedback": [{"ok": True, "params": {"trello_card_id": "c456"}}],
        }
        result = _merge_feedback(original, fire_response)
        parsed = json.loads(result)
        assert parsed["trello_card_id"] == "c456"

    def test_merge_multiple_feedbacks(self):
        """Both Todoist and Trello feedback in same response merge both IDs."""
        original = json.dumps({"status": "ok", "todoist_task_id": None, "trello_card_id": None})
        fire_response = {
            "feedback": [
                {"ok": True, "params": {"todoist_task_id": "t123"}},
                {"ok": True, "params": {"trello_card_id": "c456"}},
            ],
        }
        result = _merge_feedback(original, fire_response)
        parsed = json.loads(result)
        assert parsed["todoist_task_id"] == "t123"
        assert parsed["trello_card_id"] == "c456"

    def test_merge_failed_hook_no_change(self):
        """Feedback entry with ok=False does not modify the original result."""
        original = json.dumps({"status": "ok", "todoist_task_id": None})
        fire_response = {
            "feedback": [{"ok": False, "params": {"todoist_task_id": "t123"}}],
        }
        result = _merge_feedback(original, fire_response)
        parsed = json.loads(result)
        assert parsed["todoist_task_id"] is None

    def test_merge_no_hooks_configured(self):
        """fire_response=None returns original unchanged."""
        original = json.dumps({"status": "ok"})
        result = _merge_feedback(original, None)
        assert result == original

    def test_merge_empty_feedback_list(self):
        """Empty feedback list returns original unchanged."""
        original = json.dumps({"status": "ok"})
        fire_response = {"feedback": []}
        result = _merge_feedback(original, fire_response)
        assert result == original

    def test_merge_no_feedback_key(self):
        """fire_response dict without feedback key returns original unchanged."""
        original = json.dumps({"status": "ok"})
        fire_response = {"hooks_fired": 1, "errors": [], "results": []}
        result = _merge_feedback(original, fire_response)
        assert result == original

    def test_merge_non_json_result(self):
        """Non-JSON original_result is returned as-is."""
        original = "plain text result, not JSON"
        fire_response = {
            "feedback": [{"ok": True, "params": {"todoist_task_id": "t123"}}],
        }
        result = _merge_feedback(original, fire_response)
        assert result == original

    def test_merge_dict_result(self):
        """Original result that is a dict (not string) is returned as-is (no crash)."""
        original_dict = {"status": "ok", "todoist_task_id": None}
        fire_response = {
            "feedback": [{"ok": True, "params": {"todoist_task_id": "t123"}}],
        }
        result = _merge_feedback(original_dict, fire_response)  # type: ignore[arg-type]
        assert result == original_dict  # type: ignore[comparison-overlap]

    def test_merge_preserves_existing_values(self):
        """Existing non-null values are NOT overwritten by feedback."""
        original = json.dumps({"status": "ok", "todoist_task_id": "existing"})
        fire_response = {
            "feedback": [{"ok": True, "params": {"todoist_task_id": "new_value"}}],
        }
        result = _merge_feedback(original, fire_response)
        parsed = json.loads(result)
        assert parsed["todoist_task_id"] == "existing"

    def test_merge_skips_internal_keys(self):
        """Internal routing keys (todo_id, project_name) are not merged."""
        original = json.dumps({"status": "ok", "todoist_task_id": None})
        fire_response = {
            "feedback": [
                {
                    "ok": True,
                    "params": {
                        "todoist_task_id": "t123",
                        "todo_id": "should-not-appear",
                        "project_name": "should-not-appear",
                    },
                }
            ],
        }
        result = _merge_feedback(original, fire_response)
        parsed = json.loads(result)
        assert parsed["todoist_task_id"] == "t123"
        assert "todo_id" not in parsed
        assert "project_name" not in parsed

    def test_merge_entry_missing_params_key(self):
        """Feedback entry without params key is silently skipped."""
        original = json.dumps({"status": "ok", "todoist_task_id": None})
        fire_response = {"feedback": [{"ok": True}]}  # no params
        result = _merge_feedback(original, fire_response)
        assert result == original

    def test_merge_non_dict_entry_skipped(self):
        """Non-dict feedback entries are silently skipped."""
        original = json.dumps({"status": "ok"})
        fire_response = {"feedback": ["not a dict", 42, None]}
        result = _merge_feedback(original, fire_response)
        assert result == original

    def test_merge_adds_new_keys(self):
        """Feedback can add keys that don't exist in the original result."""
        original = json.dumps({"status": "ok"})
        fire_response = {
            "feedback": [{"ok": True, "params": {"new_field": "added"}}],
        }
        result = _merge_feedback(original, fire_response)
        parsed = json.loads(result)
        assert parsed["new_field"] == "added"


# ── Wrapper integration with feedback merge ─────────────────────────────────


class TestWrapToolFnMergesFeedback:
    @pytest.mark.anyio
    async def test_wrap_tool_fn_merges_feedback(self, mock_mcp):
        """Wrapper merges feedback from dispatch response into the final tool result."""
        enable_hook_dispatch(mock_mcp)

        @mock_mcp.tool()
        async def todo_add_tool() -> str:
            return json.dumps({"id": "473", "title": "Test", "todoist_task_id": None})

        fire_response = {
            "hooks_fired": 1,
            "errors": [],
            "results": [{"hook_id": "h1", "result": "ok"}],
            "top_level": True,
            "feedback": [{"ok": True, "params": {"todoist_task_id": "t999"}}],
        }
        with patch(
            "hook_dispatch.dispatch._dispatch_hook",
            new_callable=AsyncMock,
            return_value=fire_response,
        ):
            result = await mock_mcp._registered_tools["todo_add_tool"]()

        parsed = json.loads(result)
        assert parsed["todoist_task_id"] == "t999"
        assert "_hooks" in parsed
        assert parsed["_hooks"]["hooks_fired"] == 1


# ── _skip_hooks flag tests ──────────────────────────────────────────────────


@pytest.mark.anyio
async def test_skip_hooks_skips_dispatch_json_string(mock_mcp):
    """When tool returns JSON with _skip_hooks=True, _dispatch_hook is NOT called."""
    enable_hook_dispatch(mock_mcp)

    @mock_mcp.tool()
    def sync_feedback_tool() -> str:
        return json.dumps({"result": "Updated", "_skip_hooks": True})

    with patch(
        "hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None
    ) as mock_dispatch:
        result = await mock_mcp._registered_tools["sync_feedback_tool"]()

    mock_dispatch.assert_not_awaited()
    parsed = json.loads(result)
    assert parsed["_skip_hooks"] is True


@pytest.mark.anyio
async def test_skip_hooks_skips_dispatch_async(mock_mcp):
    """Async tool returning _skip_hooks=True also skips dispatch."""
    enable_hook_dispatch(mock_mcp)

    @mock_mcp.tool()
    async def async_feedback_tool() -> str:
        return json.dumps({"result": "Updated", "_skip_hooks": True})

    with patch(
        "hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None
    ) as mock_dispatch:
        result = await mock_mcp._registered_tools["async_feedback_tool"]()

    mock_dispatch.assert_not_awaited()
    parsed = json.loads(result)
    assert parsed["_skip_hooks"] is True


@pytest.mark.anyio
async def test_no_skip_hooks_dispatches_normally(mock_mcp):
    """Without _skip_hooks, dispatch proceeds as normal."""
    enable_hook_dispatch(mock_mcp)

    @mock_mcp.tool()
    def normal_tool() -> str:
        return json.dumps({"result": "Updated", "todo_id": "1"})

    with patch(
        "hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None
    ) as mock_dispatch:
        await mock_mcp._registered_tools["normal_tool"]()

    mock_dispatch.assert_awaited_once()


@pytest.mark.anyio
async def test_skip_hooks_false_dispatches_normally(mock_mcp):
    """_skip_hooks=False still dispatches hooks."""
    enable_hook_dispatch(mock_mcp)

    @mock_mcp.tool()
    def tool_with_false_skip() -> str:
        return json.dumps({"result": "Updated", "_skip_hooks": False})

    with patch(
        "hook_dispatch.dispatch._dispatch_hook", new_callable=AsyncMock, return_value=None
    ) as mock_dispatch:
        await mock_mcp._registered_tools["tool_with_false_skip"]()

    mock_dispatch.assert_awaited_once()


# ── 669: short-circuit when transport unavailable ─────────────────────────────


@pytest.mark.anyio
async def test_dispatch_short_circuits_when_transport_is_none() -> None:
    """When _resolve_hooks_transport returns (url, None), _dispatch_hook must
    skip the httpx call entirely and return the 'unreachable' envelope.

    Previously: transport=None fell through to httpx.AsyncClient default
    transport → attempted localhost:80 connect → 60s httpx timeout before
    ConnectError. Fix: return the unreachable envelope immediately.
    """
    with (
        patch(
            "hook_dispatch.dispatch._resolve_hooks_transport",
            return_value=("http://localhost/hook", None),
        ),
        patch(
            "hook_dispatch.dispatch.httpx.AsyncClient",
            side_effect=AssertionError("httpx.AsyncClient should not be constructed"),
        ),
    ):
        result = await _dispatch_hook("tool_name", json.dumps({"x": 1}))

    assert result is not None
    assert result["_error"] == "hooks server unreachable"
    assert result["hooks_fired"] == 0
