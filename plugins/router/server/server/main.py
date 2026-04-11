"""Router MCP server entrypoint."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP

from server.lib.discovery import run_discovery
from server.tools import fire as fire_tools
from server.tools import invocations as invocations_tools
from server.tools import recovery as recovery_tools
from server.tools import registry as registry_tools
from server.tools import sync as sync_tools
from server.tools import verify as verify_tools

logger = logging.getLogger("router")

mcp = FastMCP("router")
enable_hook_dispatch(
    mcp,
    exclude=[
        "router_fire_tool",
        "router_list_tool",
        "router_recover_tool",
        "router_sync_tool",
        "router_invocations_tool",
    ],
)
registry_tools.register(mcp)
fire_tools.register(mcp)
recovery_tools.register(mcp)
sync_tools.register(mcp)
verify_tools.register(mcp)
invocations_tools.register(mcp)


def _run_startup_discovery() -> None:
    """Run default-hooks auto-discovery on startup."""
    root_env = os.environ.get("HOOKS_DISCOVERY_ROOT")
    root = Path(root_env) if root_env else None

    glob_env = os.environ.get("HOOKS_DISCOVERY_GLOB")

    try:
        if glob_env:
            summary = run_discovery(root=root, glob_pattern=glob_env)
        else:
            summary = run_discovery(root=root)
        logger.info(summary)
    except Exception:
        logger.exception("Hook auto-discovery failed")


_run_startup_discovery()


def main() -> None:
    run_dual(mcp, "router", default_port=19100)


if __name__ == "__main__":
    main()
