"""Hooks MCP server entrypoint."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from server.lib.discovery import run_discovery
from server.tools import fire as fire_tools
from server.tools import recovery as recovery_tools
from server.tools import registry as registry_tools
from server.tools import sync as sync_tools
from server.tools import verify as verify_tools

logger = logging.getLogger("hooks")

mcp = FastMCP("hooks")
enable_hook_dispatch(mcp, exclude=["hooks_fire_tool", "hooks_list_tool", "hooks_recover_tool", "hooks_sync_tool"])
registry_tools.register(mcp)
fire_tools.register(mcp)
recovery_tools.register(mcp)
sync_tools.register(mcp)
verify_tools.register(mcp)


def _run_startup_discovery() -> None:
    """Run default-hooks auto-discovery on startup."""
    root_env = os.environ.get("HOOKS_DISCOVERY_ROOT")
    root = Path(root_env) if root_env else None

    glob_env = os.environ.get("HOOKS_DISCOVERY_GLOB")
    kwargs: dict[str, object] = {}
    if root is not None:
        kwargs["root"] = root
    if glob_env:
        kwargs["glob_pattern"] = glob_env

    try:
        summary = run_discovery(**kwargs)  # type: ignore[arg-type]
        logger.info(summary)
    except Exception:
        logger.exception("Hook auto-discovery failed")


_run_startup_discovery()


def main() -> None:
    run_dual(mcp, "hooks", default_port=19100)


if __name__ == "__main__":
    main()
