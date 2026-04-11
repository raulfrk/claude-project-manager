"""Run a FastMCP server with both stdio and HTTP transports simultaneously.

The HTTP endpoint enables inter-server hook communication — other MCP servers
can POST tool calls to ``/hook`` via the hooks plugin's fire mechanism.

By default, uses Unix domain sockets for transport (sandbox-friendly).
Set ``HOOK_TRANSPORT=tcp`` to fall back to TCP on 127.0.0.1.
"""

from __future__ import annotations

import atexit
import contextlib
import inspect
import logging
import os
import socket
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import uvicorn
from mcp.server.stdio import stdio_server

from hook_transport.http_hook_handler import create_hook_app

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("hook_transport.dual")

SOCKET_DIR = "/tmp"
SOCKET_PREFIX = "claude-cpm-"

_PreRunFn = Callable[[], None] | Callable[[], Coroutine[None, None, None]]


def _socket_path(plugin_name: str) -> str:
    """Return the Unix domain socket path for a plugin (PID-tagged)."""
    pid = os.getpid()
    return f"{SOCKET_DIR}/{SOCKET_PREFIX}{plugin_name}-{pid}.sock"


_SOCKET_REGISTRY_DIR = Path.home() / ".claude" / "sockets"


def _write_socket_registry(plugin_name: str, sock_path: str) -> None:
    """Write the socket path to the registry file for client discovery."""
    _SOCKET_REGISTRY_DIR.mkdir(parents=True, exist_ok=True)
    (_SOCKET_REGISTRY_DIR / plugin_name).write_text(sock_path)


def _delete_socket_registry(plugin_name: str) -> None:
    """Remove the registry file on shutdown. Swallows errors silently."""
    with contextlib.suppress(FileNotFoundError, PermissionError):
        (_SOCKET_REGISTRY_DIR / plugin_name).unlink()


def _cleanup_stale_socket(path: str) -> None:
    """Remove a stale socket file if it exists and nothing is listening on it."""
    if not Path(path).exists():
        return
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.connect(path)
        # Connected successfully — something is actively listening, don't remove
        sock.close()
        raise RuntimeError(f"Socket {path} is already in use by another process")
    except ConnectionRefusedError:
        # Nobody listening — stale socket, safe to remove
        logger.info("Removing stale socket: %s", path)
        Path(path).unlink()
    except FileNotFoundError:
        pass  # Race condition: file disappeared between exists() and connect()
    finally:
        sock.close()


def _register_socket_cleanup(path: str) -> None:
    """Register atexit handler to remove the socket file on shutdown."""

    def _cleanup() -> None:
        with contextlib.suppress(FileNotFoundError):
            Path(path).unlink()

    atexit.register(_cleanup)


async def _start_http(server: uvicorn.Server, label: str) -> None:
    """Start the uvicorn HTTP server, catching all failures gracefully.

    The HTTP endpoint is optional — if it fails to start (port conflict,
    sandbox restrictions, permission errors), the stdio transport must
    continue working.  We catch ``BaseException`` (except
    ``KeyboardInterrupt``) because uvicorn may raise ``SystemExit`` on
    bind failure and sandbox enforcement can surface as ``PermissionError``,
    ``ConnectionRefusedError``, or opaque runtime errors depending on the
    sandbox backend.
    """
    try:
        await server.serve()
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        exc_name = type(exc).__name__
        if isinstance(exc, PermissionError):
            hint = " (sandbox may be blocking socket/network bind)"
        elif isinstance(exc, OSError):
            hint = " (socket/port may already be in use)"
        else:
            hint = ""
        logger.warning(
            "HTTP hook server %s failed to start (%s: %s)%s — falling back to stdio-only transport",
            label,
            exc_name,
            exc,
            hint,
        )
        print(
            f"[hook_transport] HTTP hook server {label} unavailable "
            f"({exc_name}){hint} — stdio transport continues normally",
            file=sys.stderr,
        )


async def _run_dual_async(
    mcp_instance: FastMCP,
    plugin_name: str,
    default_port: int | None = None,
    pre_run: _PreRunFn | None = None,
) -> None:
    """Internal async implementation of dual-transport startup."""
    # Run optional pre-startup callback (e.g., hooks discovery)
    if pre_run is not None:
        if inspect.iscoroutinefunction(pre_run):
            await pre_run()
        else:
            pre_run()

    transport_mode = os.environ.get("HOOK_TRANSPORT", "unix").lower()
    hook_app = create_hook_app(mcp_instance)

    if transport_mode == "tcp":
        # Legacy TCP fallback
        port = int(os.environ.get("HOOK_HTTP_PORT", str(default_port or 19100)))
        config = uvicorn.Config(
            hook_app,
            host="127.0.0.1",
            port=port,
            log_level="warning",
        )
        label = f"tcp://127.0.0.1:{port}"
    else:
        # Unix domain socket (default)
        sock_path = _socket_path(plugin_name)
        _cleanup_stale_socket(sock_path)
        _write_socket_registry(plugin_name, sock_path)
        _register_socket_cleanup(sock_path)
        # NOTE: Do NOT delete registry on atexit — causes race condition when
        # Claude Code restarts (old process deletes registry after new process
        # writes it). Stale registry files are harmless: they point to dead
        # sockets that fail-fast on connect, and get overwritten on next start.
        config = uvicorn.Config(
            hook_app,
            uds=sock_path,
            log_level="warning",
        )
        label = f"unix://{sock_path}"

    server = uvicorn.Server(config)

    async with anyio.create_task_group() as tg:
        # Start HTTP server in background task
        tg.start_soon(_start_http, server, label)

        # Run stdio transport (blocks until stdin closes)
        async with stdio_server() as (read_stream, write_stream):
            await mcp_instance._mcp_server.run(
                read_stream,
                write_stream,
                mcp_instance._mcp_server.create_initialization_options(),
            )

        # Stdio ended — gracefully shut down HTTP server
        server.should_exit = True


def run_dual(
    mcp_instance: FastMCP,
    plugin_name: str,
    default_port: int | None = None,
    pre_run: _PreRunFn | None = None,
) -> None:
    """Run a FastMCP server with both stdio and HTTP transports.

    This replaces ``mcp.run()`` in plugin entry points. The HTTP endpoint
    enables inter-server hook communication while stdio serves Claude Code.

    Args:
        mcp_instance: The FastMCP server instance with tools registered.
        plugin_name: Plugin identifier used for the Unix socket filename.
        default_port: Default HTTP port for TCP fallback (overridable via
                      ``HOOK_HTTP_PORT`` env var). Only used when
                      ``HOOK_TRANSPORT=tcp``.
        pre_run: Optional callback invoked before transports start. Supports both
                 sync and async callables.
    """
    anyio.run(_run_dual_async, mcp_instance, plugin_name, default_port, pre_run)
