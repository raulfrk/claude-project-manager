"""Run a FastMCP server with both stdio and HTTP transports simultaneously.

The HTTP endpoint enables inter-server hook communication — other MCP servers
can POST tool calls to ``/hook`` via the hooks plugin's fire mechanism.
"""

from __future__ import annotations

import inspect
import logging
import os
import sys
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import anyio
import uvicorn
from mcp.server.stdio import stdio_server

from hook_transport.http_hook_handler import create_hook_app

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("hook_transport.dual")


async def _start_http(server: Any, port: int) -> None:
    """Start the uvicorn HTTP server, catching port-bind failures gracefully.

    Note: uvicorn internally calls sys.exit(1) on port bind failure, raising
    SystemExit rather than OSError. We catch both to handle all failure modes.
    """
    try:
        await server.serve()
    except (OSError, SystemExit) as exc:
        print(
            f"[hook_transport] HTTP hook server on port {port} failed to start: {exc}",
            file=sys.stderr,
        )


async def _run_dual_async(
    mcp_instance: FastMCP,
    default_port: int,
    pre_run: Callable[..., Any] | None = None,
) -> None:
    """Internal async implementation of dual-transport startup."""
    # Run optional pre-startup callback (e.g., hooks discovery)
    if pre_run is not None:
        if inspect.iscoroutinefunction(pre_run):
            await pre_run()
        else:
            pre_run()

    port = int(os.environ.get("HOOK_HTTP_PORT", str(default_port)))
    hook_app = create_hook_app(mcp_instance)

    config = uvicorn.Config(
        hook_app,
        host="127.0.0.1",
        port=port,
        log_level="warning",
    )
    server = uvicorn.Server(config)

    async with anyio.create_task_group() as tg:
        # Start HTTP server in background task
        tg.start_soon(_start_http, server, port)

        # Run stdio transport (blocks until stdin closes)
        async with stdio_server() as (read_stream, write_stream):
            await mcp_instance._mcp_server.run(  # noqa: SLF001
                read_stream,
                write_stream,
                mcp_instance._mcp_server.create_initialization_options(),  # noqa: SLF001
            )

        # Stdio ended — gracefully shut down HTTP server
        server.should_exit = True


def run_dual(
    mcp_instance: FastMCP,
    default_port: int,
    pre_run: Callable[..., Any] | None = None,
) -> None:
    """Run a FastMCP server with both stdio and HTTP transports.

    This replaces ``mcp.run()`` in plugin entry points. The HTTP endpoint
    enables inter-server hook communication while stdio serves Claude Code.

    Args:
        mcp_instance: The FastMCP server instance with tools registered.
        default_port: Default HTTP port (overridable via ``HOOK_HTTP_PORT`` env var).
        pre_run: Optional callback invoked before transports start. Supports both
                 sync and async callables.
    """
    anyio.run(_run_dual_async, mcp_instance, default_port, pre_run)
