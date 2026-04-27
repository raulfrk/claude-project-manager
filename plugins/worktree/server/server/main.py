"""worktree MCP server entrypoint."""

from hook_dispatch import enable_hook_dispatch
from hook_transport import port_for, run_dual
from mcp.server.fastmcp import FastMCP

from server.tools import repos, worktrees, zoxide

mcp = FastMCP("worktree")
enable_hook_dispatch(mcp)
repos.register(mcp)
worktrees.register(mcp)
zoxide.register(mcp)


def main() -> None:
    run_dual(mcp, "worktree", default_port=port_for("worktree"))


if __name__ == "__main__":
    main()
