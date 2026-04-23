"""Wiki plugin MCP server entrypoint."""

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("wiki")
enable_hook_dispatch(mcp)

# Tool modules registered in later tasks.


def main() -> None:
    run_dual(mcp, "wiki", default_port=19109)


if __name__ == "__main__":
    main()
