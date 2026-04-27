"""Todoist MCP server entrypoint."""

from hook_dispatch import enable_hook_dispatch
from hook_transport import port_for, run_dual
from mcp.server.fastmcp import FastMCP

from server.tools import init, projects, tasks

mcp = FastMCP("todoist")
enable_hook_dispatch(mcp)
init.register(mcp)
projects.register(mcp)
tasks.register(mcp)


def main() -> None:
    run_dual(mcp, "todoist", default_port=port_for("todoist"))


if __name__ == "__main__":
    main()
