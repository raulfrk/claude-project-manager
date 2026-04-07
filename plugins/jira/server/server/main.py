"""Jira MCP server entrypoint."""

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP

from server.tools import init, issues, projects

mcp = FastMCP("jira")
enable_hook_dispatch(mcp)
init.register(mcp)
issues.register(mcp)
projects.register(mcp)


def main() -> None:
    run_dual(mcp, "jira", default_port=19105)


if __name__ == "__main__":
    main()
