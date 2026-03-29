"""zoxide MCP server entrypoint."""

from mcp.server.fastmcp import FastMCP

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from server.tools import zoxide as zoxide_tools

mcp = FastMCP("zoxide")
enable_hook_dispatch(mcp)
zoxide_tools.register(mcp)


def main() -> None:
    run_dual(mcp, 19107)


if __name__ == "__main__":
    main()
