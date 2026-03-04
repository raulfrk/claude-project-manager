"""Additional MCP tool tests covering edge cases and git tools."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from server.lib import state, storage
from server.lib.models import ProjConfig
from tests.conftest import call_tool, setup_project


@pytest.fixture()
def project(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
    setup_project(cfg, "myapp", str(tmp_path))
    state.set_session_active("myapp")
    return cfg, "myapp"


@pytest.mark.asyncio
class TestGitMCPTools:
    async def test_detect_work_no_git(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        # git disabled — should return git_enabled: false
        cfg, name = project
        meta = storage.load_meta(cfg, name)
        meta.git_enabled = False
        storage.save_meta(cfg, meta)
        result = await call_tool(mcp_app, "git_detect_work")
        assert "false" in result.lower() or "False" in result

    async def test_detect_work_with_mock(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        with patch(
            "server.tools.git._git_log",
            return_value=["2026-01-01 abc1234 Fix bug (code)"],
        ), patch("server.tools.git._active_branches", return_value=["main"]):
            result = await call_tool(mcp_app, "git_detect_work", since_days=7)
        assert "Fix bug" in result
        assert "abc1234" in result
        assert "2026-01-01" in result

    async def test_detect_work_commit_format(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Commits are returned as plain-text one-liners, not JSON objects."""
        with patch(
            "server.tools.git._git_log",
            return_value=["2026-02-26 5af9a99 feat: initial skeleton (myapp)"],
        ), patch("server.tools.git._active_branches", return_value=["main"]):
            result = await call_tool(mcp_app, "git_detect_work", since_days=7)
        # One-liner format: YYYY-MM-DD sha8 subject (repo)
        assert "2026-02-26 5af9a99 feat: initial skeleton (myapp)" in result
        # Must NOT appear as a JSON object with separate fields
        assert '"sha"' not in result
        assert '"author"' not in result
        assert '"subject"' not in result

    async def test_git_link_todo(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="Feature")
        result = await call_tool(
            mcp_app, "git_link_todo", todo_id="1", branch="feat/x", commit="abc1234"
        )
        assert "1" in result
        todos = storage.load_todos(project[0], "myapp")
        assert todos[0].git.branch == "feat/x"

    async def test_git_suggest_todos_no_git(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = project
        meta = storage.load_meta(cfg, name)
        meta.git_enabled = False
        storage.save_meta(cfg, meta)
        result = await call_tool(mcp_app, "git_suggest_todos")
        assert "not enabled" in result.lower()

    async def test_git_suggest_todos_with_mock(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        with patch(
            "server.tools.git._git_log",
            return_value=["2026-01-01 aaaaaaaa Add feature X (code)"],
        ):
            result = await call_tool(mcp_app, "git_suggest_todos")
        assert "Add feature X" in result

    async def test_git_reconcile_todos_no_git(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = project
        meta = storage.load_meta(cfg, name)
        meta.git_enabled = False
        storage.save_meta(cfg, meta)
        import json
        result = await call_tool(mcp_app, "proj_git_reconcile_todos")
        data = json.loads(result)
        assert data["git_enabled"] is False
        assert data["suggestions"] == []

    async def test_git_reconcile_todos_with_mock(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        import json
        with patch(
            "server.tools.git._git_log",
            return_value=["2026-01-15 aaaaaaaa Add feature X (code)"],
        ), patch("server.tools.git._active_branches", return_value=["main", "feat/x"]):
            result = await call_tool(mcp_app, "proj_git_reconcile_todos", since_days=7)
        data = json.loads(result)
        assert data["git_enabled"] is True
        assert len(data["commits"]) == 1
        assert "feat/x" in str(data["branches"])
        assert len(data["suggestions"]) == 1
        suggestion = data["suggestions"][0]
        assert suggestion["subject"] == "Add feature X"
        assert suggestion["sha"] == "aaaaaaaa"
        assert suggestion["date"] == "2026-01-15"
        assert suggestion["repo"] == "code"

    async def test_git_reconcile_todos_no_active_project(self, mcp_app: Any, cfg: ProjConfig) -> None:
        result = await call_tool(mcp_app, "proj_git_reconcile_todos")
        assert "No active project" in result


@pytest.mark.asyncio
class TestTodosEdgeCases:
    async def test_todo_update(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="Old title")
        result = await call_tool(
            mcp_app, "todo_update", todo_id="1", title="New title", status="in_progress"
        )
        assert "Updated" in result
        todos = storage.load_todos(project[0], "myapp")
        assert todos[0].title == "New title"
        assert todos[0].status == "in_progress"

    async def test_todo_get(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="Get me")
        result = await call_tool(mcp_app, "todo_get", todo_id="1")
        assert "Get me" in result

    async def test_todo_get_not_found(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        result = await call_tool(mcp_app, "todo_get", todo_id="T999")
        assert "not found" in result.lower()

    async def test_todo_unblock(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="T1")
        await call_tool(mcp_app, "todo_add", title="T2")
        await call_tool(mcp_app, "todo_block", todo_id="1", blocks_ids=["2"])
        result = await call_tool(mcp_app, "todo_unblock", todo_id="1")
        assert "Removed" in result
        todos = storage.load_todos(project[0], "myapp")
        t1 = next(t for t in todos if t.id == "1")
        t2 = next(t for t in todos if t.id == "2")
        assert t1.blocks == []
        assert t2.blocked_by == []

    async def test_todo_list_empty(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        result = await call_tool(mcp_app, "todo_list")
        assert "No todos" in result


@pytest.mark.asyncio
class TestContextEdgeCases:
    async def test_session_start_no_active(self, mcp_app: Any, cfg: ProjConfig) -> None:
        # No project set up
        result = await call_tool(mcp_app, "ctx_session_start")
        assert result == "" or "no" in result.lower()

    async def test_session_start_compact(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(mcp_app, "ctx_session_start", compact=True)
        assert "myapp" in result

    async def test_session_end(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        result = await call_tool(mcp_app, "ctx_session_end")
        assert "Updated" in result or "myapp" in result

    async def test_ctx_session_start_with_cwd_detect(
        self, mcp_app: Any, project: tuple[ProjConfig, str], tmp_path: Path
    ) -> None:
        # Clear session active to test cwd-based auto-detection
        state.clear_session_active()
        result = await call_tool(mcp_app, "ctx_session_start", cwd=str(tmp_path))
        # Should have detected myapp via cwd and set session active
        assert "myapp" in result
        assert state.get_session_active() == "myapp"


@pytest.mark.asyncio
class TestProjectsEdgeCases:
    async def test_proj_get(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        result = await call_tool(mcp_app, "proj_get")
        assert "myapp" in result

    async def test_proj_list_includes_active_marker(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(mcp_app, "proj_list")
        assert "*" in result  # active marker

    async def test_proj_set_permissions(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        result = await call_tool(mcp_app, "proj_set_permissions", auto_grant=False)
        assert "False" in result or "false" in result.lower()
        meta = storage.load_meta(project[0], "myapp")
        assert meta.permissions.auto_grant is False
