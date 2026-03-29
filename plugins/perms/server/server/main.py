"""perms MCP server entrypoint."""

from mcp.server.fastmcp import FastMCP

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from server.tools import settings as settings_tools

mcp = FastMCP("perms")
enable_hook_dispatch(mcp)
settings_tools.register(mcp)


def main() -> None:
    run_dual(mcp, 19101)


if __name__ == "__main__":
    main()
