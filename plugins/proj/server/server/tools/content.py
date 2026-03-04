"""MCP tools for per-todo requirements and research content."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from server.lib import state, storage
from server.tools.config import require_config

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    """Register content_set_requirements, content_get_requirements, content_set_research, content_get_research, and proj_get_todo_context tools with the MCP app."""

    @app.tool(description="Write requirements.md for a todo.")
    def content_set_requirements(
        todo_id: str, content: str, project_name: str | None = None
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        storage.write_requirements(cfg, name, todo_id, content)
        return f"Written requirements.md for {todo_id}."

    @app.tool(description="Read requirements.md for a todo.")
    def content_get_requirements(
        todo_id: str, project_name: str | None = None, max_chars: int = 4000
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        result = storage.read_requirements(cfg, name, todo_id)
        if result is None:
            return f"No requirements.md found for {todo_id}."
        if len(result) > max_chars:
            file_path = storage.requirements_path(cfg, name, todo_id)
            omitted = len(result) - max_chars
            return result[:max_chars] + f"\n\n[truncated — {omitted} chars omitted. Full file at {file_path}]"
        return result

    @app.tool(description="Write research.md for a todo.")
    def content_set_research(todo_id: str, content: str, project_name: str | None = None) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        storage.write_research(cfg, name, todo_id, content)
        return f"Written research.md for {todo_id}."

    @app.tool(description="Read research.md for a todo.")
    def content_get_research(
        todo_id: str, project_name: str | None = None, max_chars: int = 4000
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        result = storage.read_research(cfg, name, todo_id)
        if result is None:
            return f"No research.md found for {todo_id}."
        if len(result) > max_chars:
            file_path = storage.research_path(cfg, name, todo_id)
            omitted = len(result) - max_chars
            return result[:max_chars] + f"\n\n[truncated — {omitted} chars omitted. Full file at {file_path}]"
        return result

    @app.tool(
        description=(
            "Return a todo's full context in one call: the todo itself, optionally its parent, "
            "requirements.md, and research.md. Replaces 3-4 separate tool calls. "
            "Returns JSON with keys: todo, parent (null if none or include_parent=false), "
            "requirements (null if not found), research (null if not found)."
        )
    )
    def proj_get_todo_context(
        todo_id: str,
        include_parent: bool = True,
        project_name: str | None = None,
        max_chars: int = 4000,
    ) -> str:
        cfg = require_config()
        name = state.resolve_project(project_name)
        if not name:
            return "No active project."
        todos = storage.load_todos(cfg, name)
        todo = next((t for t in todos if t.id == todo_id), None)
        if not todo:
            return f"Todo '{todo_id}' not found."

        parent_dict = None
        if include_parent and todo.parent:
            parent_todo = next((t for t in todos if t.id == todo.parent), None)
            if parent_todo:
                parent_dict = parent_todo.to_dict()

        def _truncate(content: str | None, file_path: object) -> str | None:
            if content is None:
                return None
            if len(content) > max_chars:
                omitted = len(content) - max_chars
                return content[:max_chars] + f"\n\n[truncated — {omitted} chars omitted. Full file at {file_path}]"
            return content

        requirements = _truncate(
            storage.read_requirements(cfg, name, todo_id),
            storage.requirements_path(cfg, name, todo_id),
        )
        research = _truncate(
            storage.read_research(cfg, name, todo_id),
            storage.research_path(cfg, name, todo_id),
        )

        return json.dumps(
            {
                "todo": todo.to_dict(),
                "parent": parent_dict,
                "requirements": requirements,
                "research": research,
            },
            indent=2,
        )
