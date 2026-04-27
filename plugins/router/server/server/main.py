"""Router MCP server entrypoint."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from hook_dispatch import enable_hook_dispatch
from hook_transport import port_for, run_dual
from mcp.server.fastmcp import FastMCP

from server.lib.discovery import run_discovery
from server.tools import fire as fire_tools
from server.tools import invocations as invocations_tools
from server.tools import recovery as recovery_tools
from server.tools import registry as registry_tools
from server.tools import sync as sync_tools
from server.tools import verify as verify_tools

logger = logging.getLogger("router")


def _resolve_active_plugins() -> set[str] | None:
    """Load active plugin names from the nearest marketplace.json.

    Returns None if the file cannot be found/parsed (disables orphan filter).
    """
    current = Path(__file__).resolve()
    for _ in range(8):
        current = current.parent
        candidate = current / ".claude-plugin" / "marketplace.json"
        if candidate.is_file():
            try:
                data = json.loads(candidate.read_text())
                plugins = data.get("plugins", [])
                return {p["name"] for p in plugins if isinstance(p, dict) and "name" in p}
            except (json.JSONDecodeError, OSError, KeyError):
                return None
    return None


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
        active_plugins = _resolve_active_plugins()
        if glob_env:
            summary = run_discovery(root=root, glob_pattern=glob_env, active_plugins=active_plugins)
        else:
            summary = run_discovery(root=root, active_plugins=active_plugins)
        logger.info(summary)
    except Exception:
        logger.warning(
            "Hook auto-discovery failed — server will start with no hooks registered. "
            "Verify HOOKS_DISCOVERY_ROOT / HOOKS_DISCOVERY_GLOB env vars.",
            exc_info=True,
        )


_run_startup_discovery()


def main() -> None:
    run_dual(mcp, "router", default_port=port_for("router"))


if __name__ == "__main__":
    main()
