"""Tests for dual_transport — stdio + HTTP transport orchestration."""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import anyio
import pytest

from hook_transport.dual_transport import _run_dual_async, _start_http


# ── _start_http tests ────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_start_http_port_bind_failure(capsys):
    """Port bind failure logs to stderr and returns cleanly (no crash)."""
    server = AsyncMock()
    server.serve = AsyncMock(side_effect=OSError("Address already in use"))
    await _start_http(server, 19999)
    captured = capsys.readouterr()
    assert "19999" in captured.err
    assert "failed to start" in captured.err


@pytest.mark.anyio
async def test_start_http_port_bind_system_exit(capsys):
    """uvicorn calls sys.exit(1) on port bind failure — caught as SystemExit."""
    server = AsyncMock()
    server.serve = AsyncMock(side_effect=SystemExit(1))
    await _start_http(server, 19999)
    captured = capsys.readouterr()
    assert "19999" in captured.err
    assert "failed to start" in captured.err


@pytest.mark.anyio
async def test_start_http_calls_serve():
    """Normal case: server.serve() is awaited."""
    server = AsyncMock()
    server.serve = AsyncMock(return_value=None)
    await _start_http(server, 19100)
    server.serve.assert_awaited_once()


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
    ):
        mock_create.return_value = MagicMock()

        mock_server = AsyncMock()
        mock_server.serve = AsyncMock(return_value=None)
        mock_server.should_exit = False
        mock_uvicorn.Config.return_value = MagicMock()
        mock_uvicorn.Server.return_value = mock_server

        # Simulate stdio ending immediately
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=(MagicMock(), MagicMock()))
        mock_ctx.__aexit__ = AsyncMock(return_value=False)
        mock_stdio.return_value = mock_ctx

        mock_mcp = MagicMock()
        mock_mcp._mcp_server.run = AsyncMock(return_value=None)
        mock_mcp._mcp_server.create_initialization_options.return_value = {}

        await _run_dual_async(mock_mcp, 19100, pre_run=my_pre_run)

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

        await _run_dual_async(mock_mcp, 19100, pre_run=my_async_pre_run)

    assert called == ["async"]


@pytest.mark.anyio
async def test_pre_run_none_is_noop():
    """pre_run=None is silently skipped."""
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

        # Should not raise
        await _run_dual_async(mock_mcp, 19100, pre_run=None)


@pytest.mark.anyio
async def test_port_from_env_var(monkeypatch):
    """HOOK_HTTP_PORT env var overrides default_port."""
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

        await _run_dual_async(mock_mcp, 19100)

    # Verify uvicorn.Config was called with env port
    mock_uvicorn.Config.assert_called_once()
    call_kwargs = mock_uvicorn.Config.call_args
    assert call_kwargs.kwargs.get("port") == 19999 or call_kwargs[1].get("port") == 19999


@pytest.mark.anyio
async def test_port_fallback_to_default():
    """Without HOOK_HTTP_PORT, uses default_port."""
    env = os.environ.copy()
    env.pop("HOOK_HTTP_PORT", None)

    with (
        patch.dict(os.environ, env, clear=True),
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

        await _run_dual_async(mock_mcp, 19101)

    mock_uvicorn.Config.assert_called_once()
    call_kwargs = mock_uvicorn.Config.call_args
    assert call_kwargs.kwargs.get("port") == 19101 or call_kwargs[1].get("port") == 19101


@pytest.mark.anyio
async def test_http_binds_localhost_only():
    """HTTP server binds to 127.0.0.1 only."""
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

        await _run_dual_async(mock_mcp, 19100)

    call_kwargs = mock_uvicorn.Config.call_args
    assert call_kwargs.kwargs.get("host") == "127.0.0.1" or call_kwargs[1].get("host") == "127.0.0.1"


@pytest.mark.anyio
async def test_stdio_shutdown_sets_should_exit():
    """After stdio ends, server.should_exit is set to True."""
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

        await _run_dual_async(mock_mcp, 19100)

    assert mock_server.should_exit is True
