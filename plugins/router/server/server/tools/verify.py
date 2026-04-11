"""MCP tool for explicitly firing verification hooks."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from server.lib import storage
from server.lib.conditions import _load_proj_config
from server.tools.fire import _fire_verification

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

    from server.lib._types import JsonValue
    from server.lib.models import Hook

logger = logging.getLogger(__name__)


# ── Core logic ────────────────────────────────────────────────────────────────


async def hooks_verify(
    trigger_tool: str,
    source_result: str = "{}",
) -> str:
    """Explicitly fire only verification hooks for a trigger tool.

    *source_result* is a JSON string representing context passed to verification
    hooks (e.g. Phase 1 results or original trigger output).

    Returns a JSON summary with per-hook results and a pass/fail tally.
    """
    # Parse source_result
    try:
        source: dict[str, JsonValue] = json.loads(source_result)
        if not isinstance(source, dict):
            return "Error: source_result must be a JSON object, got " + type(source).__name__
    except json.JSONDecodeError as e:
        return f"Error: source_result is not valid JSON: {e}"

    # Build merged config for condition evaluation
    base_config = _load_proj_config()
    if source:
        # Inject todo-level fields
        todo_fields = {
            k: v
            for k, v in source.items()
            if k
            in (
                "todoist_task_id",
                "trello_card_id",
                "trello_checklist_id",
                "trello_checklist_item_id",
                "jira_issue_key",
            )
        }
        if todo_fields:
            todo_section = base_config.get("todo")
            if not isinstance(todo_section, dict):
                todo_section = {}
                base_config["todo"] = todo_section
            todo_section.update(todo_fields)
        # Inject project-level fields
        project_fields = {
            k: v
            for k, v in source.items()
            if k
            in (
                "todoist_project_id",
                "trello_card_id",
                "trello_checklist_id",
            )
        }
        if project_fields:
            project_section = base_config.get("project")
            if not isinstance(project_section, dict):
                project_section = {}
                base_config["project"] = project_section
            project_section.update(project_fields)

    registry = storage.load()
    verification_hooks: list[Hook] = [
        h for h in registry.hooks if h.trigger_tool == trigger_tool and h.verification
    ]

    if not verification_hooks:
        return json.dumps({"status": "no_verification_hooks", "trigger": trigger_tool})

    results = await _fire_verification(
        hooks=verification_hooks,
        enriched_source=source,
        trigger_tool=trigger_tool,
        raw_source_result=source_result,
        config=base_config,
    )

    # Build summary
    passed = sum(1 for r in results if r["status"] == "pass")
    failed = sum(1 for r in results if r["status"] != "pass")

    return json.dumps(
        {
            "results": results,
            "summary": {
                "total": len(results),
                "passed": passed,
                "failed": failed,
            },
        },
        indent=2,
    )


# ── Registration ──────────────────────────────────────────────────────────────


def register(app: FastMCP) -> None:
    """Register the hooks_verify tool with the MCP application."""

    @app.tool(
        description=(
            "Explicitly fire only verification hooks for a given trigger_tool. "
            "source_result is a JSON string of context passed to verification hooks "
            "(e.g. Phase 1 hook results or original trigger output). "
            "Returns JSON with per-hook results (hook_id, status, details) and a "
            "summary (total, passed, failed). "
            "If no verification hooks are registered for the trigger, returns "
            "{status: 'no_verification_hooks', trigger: trigger_tool}."
        )
    )
    async def router_verify_tool(
        trigger_tool: str,
        source_result: str = "{}",
    ) -> str:
        return await hooks_verify(
            trigger_tool=trigger_tool,
            source_result=source_result,
        )
