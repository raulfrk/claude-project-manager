"""Tests for dual_transport — stdio + HTTP transport orchestration."""

from __future__ import annotations

import os
import socket
import tempfile
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest
from pathlib import Path

from hook_transport.dual_transport import (
    _cleanup_stale_socket,
    _delete_socket_registry,
    _run_dual_async,
    _socket_path,
    _start_http,
    _write_socket_registry,
)


# ── _start_http tests ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_start_http_socket_bind_failure(capsys):
    """Socket bind failure logs to stderr and returns cleanly (no crash)."""
    server = AsyncMock()
    server.serve = AsyncMock(side_effect=OSError("Address already in use"))
    await _start_http(server, "unix:///tmp/test.sock")
    captured = capsys.readouterr()
    assert "test.sock" in captured.err
    assert "unavailable" in captured.err


@pytest.mark.anyio
async def test_start_http_system_exit(capsys):
    """uvicorn calls sys.exit(1) on bind failure — caught as SystemExit."""
    server = AsyncMock()
    server.serve = AsyncMock(side_effect=SystemExit(1))
    await _start_http(server, "unix:///tmp/test.sock")
    captured = capsys.readouterr()
    assert "test.sock" in captured.err
    assert "unavailable" in captured.err


@pytest.mark.anyio
async def test_start_http_calls_serve():
    """Normal case: server.serve() is awaited."""
    server = AsyncMock()
    server.serve = AsyncMock(return_value=None)
    await _start_http(server, "unix:///tmp/test.sock")
    server.serve.assert_awaited_once()


# ── _socket_path tests ──────────────────────────────────────────────────────


def test_socket_path_format():
    """Socket path follows expected PID-tagged format."""
    path = _socket_path("hooks")
    assert path.startswith("/tmp/claude-hooks-hooks-")
    assert path.endswith(".sock")
    assert str(os.getpid()) in path


# ── _cleanup_stale_socket tests ─────────────────────────────────────────────


def test_cleanup_stale_socket_nonexistent():
    """No error when socket file doesn't exist."""
    _cleanup_stale_socket("/tmp/nonexistent-test-socket.sock")


def test_cleanup_stale_socket_removes_stale():
    """Removes a socket file that nobody is listening on."""
    with tempfile.NamedTemporaryFile(suffix=".sock", delete=False) as f:
        path = f.name
    try:
        # Create a socket file but don't listen on it — simulates stale
        os.unlink(path)
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.bind(path)
        sock.close()  # Close without listening — makes it stale
        assert os.path.exists(path)
        _cleanup_stale_socket(path)
        assert not os.path.exists(path)
    finally:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def test_cleanup_stale_socket_raises_if_active():
    """Raises RuntimeError when a process is actively listening."""
    with tempfile.NamedTemporaryFile(suffix=".sock", delete=False) as f:
        path = f.name
    os.unlink(path)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(path)
        sock.listen(1)
        with pytest.raises(RuntimeError, match="already in use"):
            _cleanup_stale_socket(path)
    finally:
        sock.close()
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


# ── _run_dual_async tests ────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_pre_run_sync_callback_invoked():
    """Sync pre_run callback is called before transports start."""
    called = []

    def my_pre_run():
        called.append("sync")

    with (
        patch("hook_transport.dual_transport.stdio_server") as mock_stdio,
        patch("hook_transport.dual_transport.uvicorn") as mock_uvicorn,
        patch("hook_transport.dual_transport.create_hook_app") as mock_create,
        patch("hook_transport.dual_transport._cleanup_stale_socket"),
        patch("hook_transport.dual_transport._register_socket_cleanup"),
    ):
        mock_create.return_value = MagicMock()

        mock_server = AsyncMock()
        mock_server.serve = AsyncMock(return_value=None)
        mock_server.should_exit = False
        mock_uvicorn.Config.return_value = MagicMock()
        mock_uvicorn.Server.return_value = mock_server

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_stdio.return_value = mock_ctx

        mock_mcp = MagicMock()
        mock_mcp._mcp_server.run = AsyncMock(return_value=None)
        mock_mcp._mcp_server.create_initialization_options.return_value = {}

        await _run_dual_async(mock_mcp, "hooks", default_port=19100, pre_run=my_pre_run)

    assert called == ["sync"]


@pytest.mark.anyio
async def test_pre_run_async_callback_invoked():
    """Async pre_run callback is awaited before transports start."""
    called = []

    async def my_async_pre_run():
        called.append("async")

    with (
        patch("hook_transport.dual_transport.stdio_server") as mock_stdio,
        patch("hook_transport.dual_transport.uvicorn") as mock_uvicorn,
        patch("hook_transport.dual_transport.create_hook_app") as mock_create,
        patch("hook_transport.dual_transport._cleanup_stale_socket"),
        patch("hook_transport.dual_transport._register_socket_cleanup"),
    ):
        mock_create.return_value = MagicMock()

        mock_server = AsyncMock()
        mock_server.serve = AsyncMock(return_value=None)
        mock_server.should_exit = False
        mock_uvicorn.Config.return_value = MagicMock()
        mock_uvicorn.Server.return_value = mock_server

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_stdio.return_value = mock_ctx

        mock_mcp = MagicMock()
        mock_mcp._mcp_server.run = AsyncMock(return_value=None)
        mock_mcp._mcp_server.create_initialization_options.return_value = {}

        await _run_dual_async(mock_mcp, "hooks", default_port=19100, pre_run=my_async_pre_run)

    assert called == ["async"]


@pytest.mark.anyio
async def test_pre_run_none_is_noop():
    """pre_run=None is silently skipped."""
    with (
        patch("hook_transport.dual_transport.stdio_server") as mock_stdio,
        patch("hook_transport.dual_transport.uvicorn") as mock_uvicorn,
        patch("hook_transport.dual_transport.create_hook_app") as mock_create,
        patch("hook_transport.dual_transport._cleanup_stale_socket"),
        patch("hook_transport.dual_transport._register_socket_cleanup"),
    ):
        mock_create.return_value = MagicMock()

        mock_server = AsyncMock()
        mock_server.serve = AsyncMock(return_value=None)
        mock_server.should_exit = False
        mock_uvicorn.Config.return_value = MagicMock()
        mock_uvicorn.Server.return_value = mock_server

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_stdio.return_value = mock_ctx

        mock_mcp = MagicMock()
        mock_mcp._mcp_server.run = AsyncMock(return_value=None)
        mock_mcp._mcp_server.create_initialization_options.return_value = {}

        # Should not raise
        await _run_dual_async(mock_mcp, "hooks", default_port=19100, pre_run=None)


@pytest.mark.anyio
async def test_default_uses_unix_socket():
    """Default transport mode uses Unix domain socket, not TCP."""
    env = os.environ.copy()
    env.pop("HOOK_TRANSPORT", None)

    with (
        patch.dict(os.environ, env, clear=True),
        patch("hook_transport.dual_transport.stdio_server") as mock_stdio,
        patch("hook_transport.dual_transport.uvicorn") as mock_uvicorn,
        patch("hook_transport.dual_transport.create_hook_app") as mock_create,
        patch("hook_transport.dual_transport._cleanup_stale_socket"),
        patch("hook_transport.dual_transport._register_socket_cleanup"),
    ):
        mock_create.return_value = MagicMock()

        mock_server = AsyncMock()
        mock_server.serve = AsyncMock(return_value=None)
        mock_server.should_exit = False
        mock_uvicorn.Config.return_value = MagicMock()
        mock_uvicorn.Server.return_value = mock_server

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_stdio.return_value = mock_ctx

        mock_mcp = MagicMock()
        mock_mcp._mcp_server.run = AsyncMock(return_value=None)
        mock_mcp._mcp_server.create_initialization_options.return_value = {}

        await _run_dual_async(mock_mcp, "todoist", default_port=19106)

    mock_uvicorn.Config.assert_called_once()
    call_kwargs = mock_uvicorn.Config.call_args
    expected_path = _socket_path("todoist")
    assert call_kwargs.kwargs.get("uds") == expected_path
    assert "host" not in call_kwargs.kwargs
    assert "port" not in call_kwargs.kwargs


@pytest.mark.anyio
async def test_tcp_fallback_via_env(monkeypatch):
    """HOOK_TRANSPORT=tcp uses port-based transport."""
    monkeypatch.setenv("HOOK_TRANSPORT", "tcp")

    with (
        patch("hook_transport.dual_transport.stdio_server") as mock_stdio,
        patch("hook_transport.dual_transport.uvicorn") as mock_uvicorn,
        patch("hook_transport.dual_transport.create_hook_app") as mock_create,
    ):
        mock_create.return_value = MagicMock()

        mock_server = AsyncMock()
        mock_server.serve = AsyncMock(return_value=None)
        mock_server.should_exit = False
        mock_uvicorn.Config.return_value = MagicMock()
        mock_uvicorn.Server.return_value = mock_server

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_stdio.return_value = mock_ctx

        mock_mcp = MagicMock()
        mock_mcp._mcp_server.run = AsyncMock(return_value=None)
        mock_mcp._mcp_server.create_initialization_options.return_value = {}

        await _run_dual_async(mock_mcp, "hooks", default_port=19100)

    mock_uvicorn.Config.assert_called_once()
    call_kwargs = mock_uvicorn.Config.call_args
    assert call_kwargs.kwargs.get("host") == "127.0.0.1"
    assert call_kwargs.kwargs.get("port") == 19100


@pytest.mark.anyio
async def test_tcp_port_from_env_var(monkeypatch):
    """HOOK_HTTP_PORT env var overrides default_port in TCP mode."""
    monkeypatch.setenv("HOOK_TRANSPORT", "tcp")
    monkeypatch.setenv("HOOK_HTTP_PORT", "19999")

    with (
        patch("hook_transport.dual_transport.stdio_server") as mock_stdio,
        patch("hook_transport.dual_transport.uvicorn") as mock_uvicorn,
        patch("hook_transport.dual_transport.create_hook_app") as mock_create,
    ):
        mock_create.return_value = MagicMock()

        mock_server = AsyncMock()
        mock_server.serve = AsyncMock(return_value=None)
        mock_server.should_exit = False
        mock_uvicorn.Config.return_value = MagicMock()
        mock_uvicorn.Server.return_value = mock_server

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_stdio.return_value = mock_ctx

        mock_mcp = MagicMock()
        mock_mcp._mcp_server.run = AsyncMock(return_value=None)
        mock_mcp._mcp_server.create_initialization_options.return_value = {}

        await _run_dual_async(mock_mcp, "hooks", default_port=19100)

    call_kwargs = mock_uvicorn.Config.call_args
    assert call_kwargs.kwargs.get("port") == 19999


@pytest.mark.anyio
async def test_stdio_shutdown_sets_should_exit():
    """After stdio ends, server.should_exit is set to True."""
    with (
        patch("hook_transport.dual_transport.stdio_server") as mock_stdio,
        patch("hook_transport.dual_transport.uvicorn") as mock_uvicorn,
        patch("hook_transport.dual_transport.create_hook_app") as mock_create,
        patch("hook_transport.dual_transport._cleanup_stale_socket"),
        patch("hook_transport.dual_transport._register_socket_cleanup"),
    ):
        mock_create.return_value = MagicMock()

        mock_server = AsyncMock()
        mock_server.serve = AsyncMock(return_value=None)
        mock_server.should_exit = False
        mock_uvicorn.Config.return_value = MagicMock()
        mock_uvicorn.Server.return_value = mock_server

        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_stdio.return_value = mock_ctx

        mock_mcp = MagicMock()
        mock_mcp._mcp_server.run = AsyncMock(return_value=None)
        mock_mcp._mcp_server.create_initialization_options.return_value = {}

        await _run_dual_async(mock_mcp, "hooks", default_port=19100)

    assert mock_server.should_exit is True


# ── Socket registry tests ──────────────────────────────────────────────────


class TestSocketRegistry:
    def test_write_creates_registry_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hook_transport.dual_transport._SOCKET_REGISTRY_DIR", tmp_path)
        _write_socket_registry("hooks", "/tmp/claude-hooks-hooks-12345.sock")
        registry_file = tmp_path / "hooks"
        assert registry_file.exists()
        assert registry_file.read_text() == "/tmp/claude-hooks-hooks-12345.sock"

    def test_delete_removes_registry_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hook_transport.dual_transport._SOCKET_REGISTRY_DIR", tmp_path)
        registry_file = tmp_path / "hooks"
        registry_file.write_text("/tmp/some-socket.sock")
        _delete_socket_registry("hooks")
        assert not registry_file.exists()

    def test_delete_silently_handles_missing_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("hook_transport.dual_transport._SOCKET_REGISTRY_DIR", tmp_path)
        # Should not raise
        _delete_socket_registry("hooks")

    @pytest.mark.anyio
    async def test_run_dual_async_writes_registry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Registry file is written when Unix socket is bound."""
        monkeypatch.setattr("hook_transport.dual_transport._SOCKET_REGISTRY_DIR", tmp_path)

        with (
            patch("hook_transport.dual_transport.stdio_server") as mock_stdio,
            patch("hook_transport.dual_transport.uvicorn") as mock_uvicorn,
            patch("hook_transport.dual_transport.create_hook_app") as mock_create,
            patch("hook_transport.dual_transport._cleanup_stale_socket"),
            patch("hook_transport.dual_transport._register_socket_cleanup"),
        ):
            mock_create.return_value = MagicMock()

            mock_server = AsyncMock()
            mock_server.serve = AsyncMock(return_value=None)
            mock_server.should_exit = False
            mock_uvicorn.Config.return_value = MagicMock()
            mock_uvicorn.Server.return_value = mock_server

            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_stdio.return_value = mock_ctx

            mock_mcp = MagicMock()
            mock_mcp._mcp_server.run = AsyncMock(return_value=None)
            mock_mcp._mcp_server.create_initialization_options.return_value = {}

            await _run_dual_async(mock_mcp, "hooks", default_port=19100)

        registry_file = tmp_path / "hooks"
        assert registry_file.exists()
        content = registry_file.read_text()
        assert "hooks" in content
        assert str(os.getpid()) in content
