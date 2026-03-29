"""Trello MCP server entrypoint."""

from mcp.server.fastmcp import FastMCP

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from server.tools import (
    attachments,
    boards,
    cards,
    checklists,
    comments,
    init,
    labels,
    lists,
    members,
)

mcp = FastMCP("trello")
enable_hook_dispatch(mcp)
init.register(mcp)
boards.register(mcp)
lists.register(mcp)
cards.register(mcp)
labels.register(mcp)
members.register(mcp)
comments.register(mcp)
checklists.register(mcp)
attachments.register(mcp)


def main() -> None:
    run_dual(mcp, 19104)


if __name__ == "__main__":
    main()
