"""worktree MCP server entrypoint."""

from mcp.server.fastmcp import FastMCP

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from server.tools import repos, worktrees

mcp = FastMCP("worktree")
enable_hook_dispatch(mcp)
repos.register(mcp)
worktrees.register(mcp)


def main() -> None:
    run_dual(mcp, 19103)


if __name__ == "__main__":
    main()
