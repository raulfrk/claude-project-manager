"""Jira MCP server entrypoint."""

from hook_dispatch import enable_hook_dispatch
from hook_transport import port_for, run_dual
from mcp.server.fastmcp import FastMCP

from server.tools import (
    attachments,
    comments,
    components,
    init,
    issues,
    labels,
    links,
    metadata,
    projects,
    sprints,
    transitions,
    users,
    versions,
    watchers,
    worklogs,
)

mcp = FastMCP("jira")
enable_hook_dispatch(mcp)
init.register(mcp)
issues.register(mcp)
projects.register(mcp)
attachments.register(mcp)
comments.register(mcp)
components.register(mcp)
labels.register(mcp)
links.register(mcp)
metadata.register(mcp)
sprints.register(mcp)
transitions.register(mcp)
users.register(mcp)
versions.register(mcp)
watchers.register(mcp)
worklogs.register(mcp)


def main() -> None:
    run_dual(mcp, "jira", default_port=port_for("jira"))


if __name__ == "__main__":
    main()
