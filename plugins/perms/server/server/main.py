"""perms MCP server entrypoint."""

from mcp.server.fastmcp import FastMCP

from server.tools import settings as settings_tools

mcp = FastMCP("perms")
settings_tools.register(mcp)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
