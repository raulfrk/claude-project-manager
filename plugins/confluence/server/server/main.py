"""Confluence read-only MCP server entrypoint."""

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("confluence")
enable_hook_dispatch(mcp, exclude={"confluence_init"})


def main() -> None:
    run_dual(mcp, "confluence", default_port=19108)


if __name__ == "__main__":
    main()
