"""Confluence read-only MCP server entrypoint."""

from hook_dispatch import enable_hook_dispatch
from hook_transport import port_for, run_dual
from mcp.server.fastmcp import FastMCP

from server.tools import attachments, comments, init, pages, search, spaces

mcp = FastMCP("confluence")
enable_hook_dispatch(mcp, exclude={"confluence_init"})

init.register(mcp)
pages.register(mcp)
search.register(mcp)
spaces.register(mcp)
attachments.register(mcp)
comments.register(mcp)


def main() -> None:
    run_dual(mcp, "confluence", default_port=port_for("confluence"))


if __name__ == "__main__":
    main()
