"""Additional MCP tool tests covering edge cases and git tools."""

from __future__ import annotations

import json as _json
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
        with (
            patch(
                "server.tools.git._git_log",
                return_value=["2026-01-01 abc1234 Fix bug (code)"],
            ),
            patch("server.tools.git._active_branches", return_value=["main"]),
        ):
            result = await call_tool(mcp_app, "git_detect_work", since_days=7)
        assert "Fix bug" in result
        assert "abc1234" in result
        assert "2026-01-01" in result

    async def test_detect_work_commit_format(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Commits are returned as plain-text one-liners, not JSON objects."""
        with (
            patch(
                "server.tools.git._git_log",
                return_value=["2026-02-26 5af9a99 feat: initial skeleton (myapp)"],
            ),
            patch("server.tools.git._active_branches", return_value=["main"]),
        ):
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

        with (
            patch(
                "server.tools.git._git_log",
                return_value=["2026-01-15 aaaaaaaa Add feature X (code)"],
            ),
            patch("server.tools.git._active_branches", return_value=["main", "feat/x"]),
        ):
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

    async def test_git_reconcile_todos_no_active_project(
        self, mcp_app: Any, cfg: ProjConfig
    ) -> None:
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

    async def test_todo_unblock(self, mcp_app: Any, project: tuple[ProjConfig, str]) -> None:
        await call_tool(mcp_app, "todo_add", title="T1")
        await call_tool(mcp_app, "todo_add", title="T2")
        # Set T2 blocked_by T1 using new API
        await call_tool(mcp_app, "todo_update", todo_id="2", blocked_by_set=["1"])
        # Clear T2's blockers using blocked_by_set=[]
        result = await call_tool(mcp_app, "todo_update", todo_id="2", blocked_by_set=[])
        import json as _json2

        data = _json2.loads(result)
        assert "Updated" in data.get("result", "")
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


# ---------------------------------------------------------------------------
# Gap tests: todo_list compact/max_items/tag/blocked filters
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTodoListFilters:
    @pytest.fixture()
    def project(self, cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        return cfg, "myapp"

    async def test_todo_list_compact_mode(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """compact=True returns pipe-delimited summaries."""
        await call_tool(mcp_app, "todo_add", title="Task A", priority="high")
        await call_tool(mcp_app, "todo_add", title="Task B", tags=["review"])
        result = await call_tool(mcp_app, "todo_list", compact=True)
        data = _json.loads(result)
        assert data["count"] == 2
        assert "Task A" in data["result"]
        assert "high" in data["result"]
        assert "|" in data["result"]

    async def test_todo_list_max_items_truncates(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """max_items truncates output and reports truncation count."""
        for i in range(5):
            await call_tool(mcp_app, "todo_add", title=f"Task {i}")
        result = await call_tool(mcp_app, "todo_list", max_items=2)
        # Non-compact mode: JSON array followed by truncation note
        assert "3 more items" in result

    async def test_todo_list_compact_max_items(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """compact + max_items together."""
        for i in range(4):
            await call_tool(mcp_app, "todo_add", title=f"Task {i}")
        result = await call_tool(mcp_app, "todo_list", compact=True, max_items=2)
        data = _json.loads(result)
        assert data["count"] == 2
        assert data["truncated"] == 2

    async def test_todo_list_tag_filter(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """tag filter returns only todos with the specified tag."""
        await call_tool(mcp_app, "todo_add", title="Tagged", tags=["urgent"])
        await call_tool(mcp_app, "todo_add", title="Untagged")
        result = await call_tool(mcp_app, "todo_list", tag="urgent")
        todos = _json.loads(result)
        assert len(todos) == 1
        assert todos[0]["title"] == "Tagged"

    async def test_todo_list_blocked_filter(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """blocked=True returns only blocked todos."""
        await call_tool(mcp_app, "todo_add", title="Blocker")
        await call_tool(mcp_app, "todo_add", title="Blocked", blocked_by=["1"])
        result = await call_tool(mcp_app, "todo_list", blocked=True)
        todos = _json.loads(result)
        assert len(todos) == 1
        assert todos[0]["title"] == "Blocked"

    async def test_todo_list_blocked_false_filter(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """blocked=False returns only unblocked todos."""
        await call_tool(mcp_app, "todo_add", title="Free")
        await call_tool(mcp_app, "todo_add", title="Blocked", blocked_by=["1"])
        result = await call_tool(mcp_app, "todo_list", blocked=False)
        todos = _json.loads(result)
        assert len(todos) == 1
        assert todos[0]["title"] == "Free"


# ---------------------------------------------------------------------------
# Gap tests: todo_ready compact mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTodoReadyCompact:
    @pytest.fixture()
    def project(self, cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        return cfg, "myapp"

    async def test_todo_ready_compact_with_results(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """compact=True returns pipe-delimited lines wrapped in a JSON envelope."""
        await call_tool(mcp_app, "todo_add", title="Ready A", priority="high")
        await call_tool(mcp_app, "todo_add", title="Ready B", tags=["review"])
        result = await call_tool(mcp_app, "todo_ready", compact=True)
        data = _json.loads(result)
        assert data["count"] == 2
        assert data["truncated"] == 0
        assert "Ready A" in data["result"]
        assert "Ready B" in data["result"]
        assert "|" in data["result"]
        # Each line shape: "<id> | <status> | <title> | <priority> | <tags>"
        assert data["result"].count("\n") == 1  # 2 todos -> 1 newline

    async def test_todo_ready_compact_empty(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """compact=True with no ready todos returns the plain string, not JSON."""
        result = await call_tool(mcp_app, "todo_ready", compact=True)
        assert result == "No todos ready to start."

    async def test_todo_ready_compact_parity(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """compact and non-compact responses cover the same set of todo IDs."""
        await call_tool(mcp_app, "todo_add", title="Alpha")
        await call_tool(mcp_app, "todo_add", title="Beta")
        await call_tool(mcp_app, "todo_add", title="Gamma")

        raw = await call_tool(mcp_app, "todo_ready")
        compact_raw = await call_tool(mcp_app, "todo_ready", compact=True)

        full_ids = {t["id"] for t in _json.loads(raw)}
        compact_data = _json.loads(compact_raw)
        compact_ids = {line.split(" | ", 1)[0] for line in compact_data["result"].split("\n")}

        assert full_ids == compact_ids
        assert compact_data["count"] == len(full_ids)


# ---------------------------------------------------------------------------
# Gap tests: todo_add / todo_update empty due_date validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestDueDateValidation:
    @pytest.fixture()
    def project(self, cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        return cfg, "myapp"

    async def test_todo_add_empty_due_date_returns_error(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Empty string due_date on todo_add is rejected."""
        result = await call_tool(mcp_app, "todo_add", title="Bad", due_date="")
        data = _json.loads(result)
        assert "error" in data
        assert "due_date" in data["error"]

    async def test_todo_update_empty_due_date_returns_error(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Empty string due_date on todo_update is rejected."""
        await call_tool(mcp_app, "todo_add", title="Task")
        result = await call_tool(mcp_app, "todo_update", todo_id="1", due_date="")
        assert "due_date cannot be empty" in result


# ---------------------------------------------------------------------------
# Gap tests: todo_uncomplete archived + todo_complete not found
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTodoCompletionEdgeCases:
    @pytest.fixture()
    def project(self, cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        return cfg, "myapp"

    async def test_todo_uncomplete_archived_returns_error(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Uncompleting an archived todo is rejected."""
        await call_tool(mcp_app, "todo_add", title="Leaf")
        await call_tool(mcp_app, "todo_complete", todo_id="1")
        # Todo is now archived
        result = await call_tool(mcp_app, "todo_uncomplete", todo_id="1")
        data = _json.loads(result)
        assert "error" in data
        assert "archived" in data["error"]

    async def test_todo_complete_not_found_returns_error(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Completing a nonexistent todo returns not found."""
        result = await call_tool(mcp_app, "todo_complete", todo_id="999")
        assert "not found" in result.lower()


# ---------------------------------------------------------------------------
# Tests moved from test_tools_integration: context._read_recent_notes
# ---------------------------------------------------------------------------


class TestReadRecentNotes:
    def test_returns_last_three_sections(self, tmp_path: Path) -> None:
        from server.tools.context import _read_recent_notes

        notes_file = tmp_path / "NOTES.md"
        notes_file.write_text(
            "## 2026-01-01\n\nFirst entry\n\n"
            "## 2026-01-02\n\nSecond entry\n\n"
            "## 2026-01-03\n\nThird entry\n\n"
            "## 2026-01-04\n\nFourth entry\n"
        )
        result = _read_recent_notes(notes_file)
        assert "Fourth entry" in result
        assert "Third entry" in result
        assert "Second entry" in result
        assert "First entry" not in result

    def test_no_dated_headers_fallback(self, tmp_path: Path) -> None:
        from server.tools.context import _read_recent_notes

        notes_file = tmp_path / "NOTES.md"
        notes_file.write_text("# Project Notes\n\nSome plain content without dated sections.\n")
        result = _read_recent_notes(notes_file, max_chars=600)
        assert "plain content" in result

    def test_empty_file(self, tmp_path: Path) -> None:
        from server.tools.context import _read_recent_notes

        notes_file = tmp_path / "NOTES.md"
        notes_file.write_text("")
        result = _read_recent_notes(notes_file)
        assert result == ""

    def test_nonexistent_file(self, tmp_path: Path) -> None:
        from server.tools.context import _read_recent_notes

        notes_file = tmp_path / "DOES_NOT_EXIST.md"
        result = _read_recent_notes(notes_file)
        assert result == ""
