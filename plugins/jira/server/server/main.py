"""Jira MCP server entrypoint."""

from mcp.server.fastmcp import FastMCP

from server.tools import init, issues, projects

mcp = FastMCP("jira")
init.register(mcp)
issues.register(mcp)
projects.register(mcp)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
