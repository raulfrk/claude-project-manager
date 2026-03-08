"""proj MCP server entrypoint."""

import os

from mcp.server.fastmcp import FastMCP

from server.lib import state
from server.tools import config, content, context, explore, git, migrate, perms_grant, perms_sync, projects, todoist_sync, todos, tracking_git
from server.tools.context import ctx_detect_project_name

mcp = FastMCP("proj")
config.register(mcp)
projects.register(mcp)
todos.register(mcp)
todoist_sync.register(mcp)
content.register(mcp)
git.register(mcp)
context.register(mcp)
migrate.register(mcp)
perms_sync.register(mcp)
perms_grant.register(mcp)
explore.register(mcp)
tracking_git.register(mcp)


def main() -> None:
    # Auto-detect active project from CLAUDE_PROJECT_DIR on startup.
    # Each MCP server process is session-isolated, so this is safe for parallel sessions.
    cwd = os.getenv("CLAUDE_PROJECT_DIR", "")
    if cwd:
        try:
            detected = ctx_detect_project_name(cwd)
            if detected:
                state.set_session_active(detected)
        except Exception:
            pass  # graceful no-op: missing config, untracked dir, etc.
    mcp.run()


if __name__ == "__main__":
    main()
