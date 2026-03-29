"""Todoist MCP server entrypoint."""

from mcp.server.fastmcp import FastMCP

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from server.tools import init, projects, tasks

mcp = FastMCP("todoist")
enable_hook_dispatch(mcp)
init.register(mcp)
projects.register(mcp)
tasks.register(mcp)


def main() -> None:
    run_dual(mcp, "todoist", default_port=19106)


if __name__ == "__main__":
    main()
