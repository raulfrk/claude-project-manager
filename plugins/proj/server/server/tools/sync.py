"""proj_sync — unified integration dispatcher (605.6).

Replaces proj_todoist_full_sync, proj_trello_full_sync, proj_jira_full_sync
with a single tool that dispatches by integration name.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    """Register proj_sync tool."""

    @app.tool(
        description=(
            "Run a full bidirectional sync for an integration. "
            "integration: 'todoist' | 'trello' | 'jira'. "
            "Delegates to the appropriate sync implementation. "
            "Returns the same JSON envelope as the individual sync tools. "
            "retry_failures: base64-encoded retry token from a prior partial_success response. "
            "confirmed_links: todoist only — JSON list of {todo_id, todoist_task_id} to confirm. "
            "retry_failures and confirmed_links are forwarded to the integration handler."
        )
    )
    def proj_sync(
        integration: str,
        project_name: str | None = None,
        retry_failures: str | None = None,
        confirmed_links: str | None = None,
    ) -> str:
        import server.tools.jira_sync as _jira_mod
        import server.tools.todoist_full_sync as _todoist_mod
        import server.tools.trello_full_sync as _trello_mod

        dispatch = {
            "todoist": lambda: _todoist_mod._run_todoist_full_sync(
                project_name=project_name,
                retry_failures=retry_failures,
                confirmed_links=confirmed_links,
            ),
            "trello": lambda: _trello_mod._run_trello_full_sync(
                project_name=project_name,
                retry_failures=retry_failures,
            ),
            "jira": lambda: _jira_mod._run_jira_full_sync(
                project_name=project_name,
                retry_failures=retry_failures,
            ),
        }
        fn = dispatch.get(integration)
        if fn is None:
            return json.dumps(
                {"error": (f"Unknown integration '{integration}'. Use: todoist, trello, jira.")}
            )
        return fn()
