"""proj MCP server entrypoint."""

import logging
import os

from hook_dispatch import enable_hook_dispatch
from hook_transport import run_dual
from mcp.server.fastmcp import FastMCP

from server.lib import state
from server.tools import (
    config,
    content,
    context,
    decisions,
    digest,
    explore,
    git,
    jira_sync,
    knowledge,
    migrate,
    perms_grant,
    perms_sync,
    projects,
    sync,
    todoist_full_sync,
    todos,
    tracking_git,
    trello_full_sync,
    trello_sync,
)
from server.tools.context import ctx_detect_project_name

mcp = FastMCP("proj")
enable_hook_dispatch(mcp)
config.register(mcp)
projects.register(mcp)
todos.register(mcp)
todoist_full_sync.register(mcp)
trello_sync.register(mcp)
trello_full_sync.register(mcp)
jira_sync.register(mcp)
sync.register(mcp)
content.register(mcp)
git.register(mcp)
context.register(mcp)
migrate.register(mcp)
perms_sync.register(mcp)
perms_grant.register(mcp)
explore.register(mcp)
knowledge.register(mcp)
decisions.register(mcp)
digest.register(mcp)
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
            logging.getLogger(__name__).debug("Auto-detect active project failed", exc_info=True)
    run_dual(mcp, "proj", default_port=19102)


if __name__ == "__main__":
    main()
