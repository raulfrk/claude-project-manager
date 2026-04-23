"""Wiki plugin MCP server entrypoint."""

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP

from server.tools import index, links, log, page, scope

mcp = FastMCP("wiki")
enable_hook_dispatch(mcp)

page.register(mcp)
index.register(mcp)
log.register(mcp)
links.register(mcp)
scope.register(mcp)


def main() -> None:
    run_dual(mcp, "wiki", default_port=19109)


if __name__ == "__main__":
    main()
