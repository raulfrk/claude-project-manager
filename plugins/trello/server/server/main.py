"""Trello MCP server entrypoint."""

from mcp.server.fastmcp import FastMCP

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
    mcp.run()


if __name__ == "__main__":
    main()
