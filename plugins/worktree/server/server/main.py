"""worktree MCP server entrypoint."""

from mcp.server.fastmcp import FastMCP

from server.tools import repos, worktrees

mcp = FastMCP("worktree")
repos.register(mcp)
worktrees.register(mcp)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
