"""Jira MCP server entrypoint."""

from mcp.server.fastmcp import FastMCP

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from server.tools import init, issues, projects

mcp = FastMCP("jira")
enable_hook_dispatch(mcp)
init.register(mcp)
issues.register(mcp)
projects.register(mcp)


def main() -> None:
    run_dual(mcp, 19105)


if __name__ == "__main__":
    main()
