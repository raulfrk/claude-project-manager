"""Tests for proj_get_todo_context MCP tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import ProjConfig
from tests.conftest import call_tool, setup_project


@pytest.fixture()
def project(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
    setup_project(cfg, "myapp", str(tmp_path / "myrepo"))
    state.set_session_active("myapp")
    return cfg, "myapp"


async def _add_todo(mcp_app: Any, title: str, parent: str | None = None) -> str:
    """Add a todo and return its ID (parsed from 'Added todo <id>: <title>')."""
    kwargs: dict[str, Any] = {"title": title}
    if parent is not None:
        kwargs["parent"] = parent
    result = await call_tool(mcp_app, "todo_add", **kwargs)
    # result is like "Added todo 1: Fix bug" or "Added todo 1.1: Child task"
    return result.split(" ")[2].rstrip(":")


@pytest.mark.asyncio
class TestProjGetTodoContext:
    async def test_returns_todo_no_content(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        todo_id = await _add_todo(mcp_app, "Fix bug")
        result = await call_tool(mcp_app, "proj_get_todo_context", todo_id=todo_id)
        data = json.loads(result)
        assert data["todo"]["id"] == todo_id
        assert data["todo"]["title"] == "Fix bug"
        assert data["parent"] is None
        assert data["requirements"] is None
        assert data["research"] is None

    async def test_includes_requirements_when_present(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        todo_id = await _add_todo(mcp_app, "Task with reqs")
        await call_tool(mcp_app, "content_set_requirements", todo_id=todo_id, content="## Reqs\nDo X.")
        result = await call_tool(mcp_app, "proj_get_todo_context", todo_id=todo_id)
        data = json.loads(result)
        assert "Do X." in data["requirements"]
        assert data["research"] is None

    async def test_includes_research_when_present(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        todo_id = await _add_todo(mcp_app, "Task with research")
        await call_tool(mcp_app, "content_set_research", todo_id=todo_id, content="Found Y.")
        result = await call_tool(mcp_app, "proj_get_todo_context", todo_id=todo_id)
        data = json.loads(result)
        assert data["requirements"] is None
        assert "Found Y." in data["research"]

    async def test_includes_both_content_files(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        todo_id = await _add_todo(mcp_app, "Full task")
        await call_tool(mcp_app, "content_set_requirements", todo_id=todo_id, content="Requirements here.")
        await call_tool(mcp_app, "content_set_research", todo_id=todo_id, content="Research here.")
        result = await call_tool(mcp_app, "proj_get_todo_context", todo_id=todo_id)
        data = json.loads(result)
        assert "Requirements here." in data["requirements"]
        assert "Research here." in data["research"]

    async def test_includes_parent_when_present(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        parent_id = await _add_todo(mcp_app, "Parent task")
        child_id = await _add_todo(mcp_app, "Child task", parent=parent_id)
        result = await call_tool(mcp_app, "proj_get_todo_context", todo_id=child_id, include_parent=True)
        data = json.loads(result)
        assert data["parent"] is not None
        assert data["parent"]["id"] == parent_id
        assert data["parent"]["title"] == "Parent task"

    async def test_excludes_parent_when_include_parent_false(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        parent_id = await _add_todo(mcp_app, "Parent task")
        child_id = await _add_todo(mcp_app, "Child task", parent=parent_id)
        result = await call_tool(mcp_app, "proj_get_todo_context", todo_id=child_id, include_parent=False)
        data = json.loads(result)
        assert data["parent"] is None

    async def test_parent_null_for_top_level_todo(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        todo_id = await _add_todo(mcp_app, "Top level")
        result = await call_tool(mcp_app, "proj_get_todo_context", todo_id=todo_id, include_parent=True)
        data = json.loads(result)
        assert data["parent"] is None

    async def test_returns_error_for_unknown_todo(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(mcp_app, "proj_get_todo_context", todo_id="999")
        assert "not found" in result

    async def test_returns_error_when_no_active_project(
        self, mcp_app: Any, cfg: ProjConfig
    ) -> None:
        result = await call_tool(mcp_app, "proj_get_todo_context", todo_id="1")
        assert "No active project" in result

    async def test_truncates_long_requirements(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        todo_id = await _add_todo(mcp_app, "Long task")
        long_content = "X" * 5000
        await call_tool(mcp_app, "content_set_requirements", todo_id=todo_id, content=long_content)
        result = await call_tool(mcp_app, "proj_get_todo_context", todo_id=todo_id, max_chars=100)
        data = json.loads(result)
        assert "[truncated" in data["requirements"]
        assert len(data["requirements"]) < 5000

    async def test_uses_project_name_override(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        setup_project(cfg, "other", str(tmp_path / "other"))
        await call_tool(mcp_app, "todo_add", title="Other task", project_name="other")
        result = await call_tool(mcp_app, "proj_get_todo_context", todo_id="1", project_name="other")
        data = json.loads(result)
        assert data["todo"]["title"] == "Other task"
