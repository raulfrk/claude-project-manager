"""Tests for todo_notes_patch and todo_notes_append MCP tools."""

from __future__ import annotations

import json
from typing import Any

import pytest

from server.lib import state
from tests.conftest import call_tool, setup_project


@pytest.fixture()
def project_with_todo(cfg: Any, tmp_path: Any, mcp_app: Any) -> tuple[Any, str]:
    """Set up a project with one todo and return (app, todo_id)."""
    setup_project(cfg, "test-proj", str(tmp_path / "repo"))
    state.set_session_active("test-proj")
    # Add a todo
    raw = json.loads(
        pytest.importorskip("asyncio")
        .get_event_loop()
        .run_until_complete(
            call_tool(mcp_app, "todo_add", title="Test todo", project_name="test-proj")
        )
    )
    todo_id = raw["todo_id"]
    return mcp_app, todo_id


class TestTodoNotesPatch:
    @pytest.mark.anyio()
    async def test_patch_single_occurrence(self, cfg: Any, tmp_path: Any, mcp_app: Any) -> None:
        setup_project(cfg, "test-proj", str(tmp_path / "repo"))
        state.set_session_active("test-proj")
        raw = json.loads(await call_tool(mcp_app, "todo_add", title="T1", project_name="test-proj"))
        tid = raw["todo_id"]
        await call_tool(
            mcp_app, "todo_update", todo_id=tid, notes="foo bar foo baz", project_name="test-proj"
        )
        result = json.loads(
            await call_tool(
                mcp_app,
                "todo_notes_patch",
                todo_id=tid,
                find="foo",
                replace="QUX",
                project_name="test-proj",
            )
        )
        assert result["result"] == "patched"
        assert result["occurrences"] == 1
        # Verify notes
        todo_raw = json.loads(
            await call_tool(mcp_app, "todo_get", todo_id=tid, project_name="test-proj")
        )
        assert todo_raw["notes"] == "QUX bar foo baz"

    @pytest.mark.anyio()
    async def test_patch_all_occurrences(self, cfg: Any, tmp_path: Any, mcp_app: Any) -> None:
        setup_project(cfg, "test-proj", str(tmp_path / "repo"))
        state.set_session_active("test-proj")
        raw = json.loads(await call_tool(mcp_app, "todo_add", title="T1", project_name="test-proj"))
        tid = raw["todo_id"]
        await call_tool(
            mcp_app,
            "todo_update",
            todo_id=tid,
            notes="foo bar foo baz foo",
            project_name="test-proj",
        )
        result = json.loads(
            await call_tool(
                mcp_app,
                "todo_notes_patch",
                todo_id=tid,
                find="foo",
                replace="X",
                count=0,
                project_name="test-proj",
            )
        )
        assert result["result"] == "patched"
        assert result["occurrences"] == 3
        todo_raw = json.loads(
            await call_tool(mcp_app, "todo_get", todo_id=tid, project_name="test-proj")
        )
        assert todo_raw["notes"] == "X bar X baz X"

    @pytest.mark.anyio()
    async def test_patch_pattern_not_found(self, cfg: Any, tmp_path: Any, mcp_app: Any) -> None:
        setup_project(cfg, "test-proj", str(tmp_path / "repo"))
        state.set_session_active("test-proj")
        raw = json.loads(await call_tool(mcp_app, "todo_add", title="T1", project_name="test-proj"))
        tid = raw["todo_id"]
        await call_tool(
            mcp_app, "todo_update", todo_id=tid, notes="hello world", project_name="test-proj"
        )
        result = json.loads(
            await call_tool(
                mcp_app,
                "todo_notes_patch",
                todo_id=tid,
                find="missing",
                replace="X",
                project_name="test-proj",
            )
        )
        assert "error" in result
        assert "Pattern not found" in result["error"]

    @pytest.mark.anyio()
    async def test_patch_empty_notes_error(self, cfg: Any, tmp_path: Any, mcp_app: Any) -> None:
        setup_project(cfg, "test-proj", str(tmp_path / "repo"))
        state.set_session_active("test-proj")
        raw = json.loads(await call_tool(mcp_app, "todo_add", title="T1", project_name="test-proj"))
        tid = raw["todo_id"]
        result = json.loads(
            await call_tool(
                mcp_app,
                "todo_notes_patch",
                todo_id=tid,
                find="anything",
                replace="X",
                project_name="test-proj",
            )
        )
        assert "error" in result
        assert "Pattern not found" in result["error"]

    @pytest.mark.anyio()
    async def test_patch_count_2_of_3(self, cfg: Any, tmp_path: Any, mcp_app: Any) -> None:
        setup_project(cfg, "test-proj", str(tmp_path / "repo"))
        state.set_session_active("test-proj")
        raw = json.loads(await call_tool(mcp_app, "todo_add", title="T1", project_name="test-proj"))
        tid = raw["todo_id"]
        await call_tool(
            mcp_app, "todo_update", todo_id=tid, notes="aa bb aa cc aa", project_name="test-proj"
        )
        result = json.loads(
            await call_tool(
                mcp_app,
                "todo_notes_patch",
                todo_id=tid,
                find="aa",
                replace="ZZ",
                count=2,
                project_name="test-proj",
            )
        )
        assert result["result"] == "patched"
        assert result["occurrences"] == 2
        todo_raw = json.loads(
            await call_tool(mcp_app, "todo_get", todo_id=tid, project_name="test-proj")
        )
        assert todo_raw["notes"] == "ZZ bb ZZ cc aa"


class TestTodoNotesAppend:
    @pytest.mark.anyio()
    async def test_append_to_existing_notes(self, cfg: Any, tmp_path: Any, mcp_app: Any) -> None:
        setup_project(cfg, "test-proj", str(tmp_path / "repo"))
        state.set_session_active("test-proj")
        raw = json.loads(await call_tool(mcp_app, "todo_add", title="T1", project_name="test-proj"))
        tid = raw["todo_id"]
        await call_tool(
            mcp_app, "todo_update", todo_id=tid, notes="existing notes", project_name="test-proj"
        )
        result = json.loads(
            await call_tool(
                mcp_app,
                "todo_notes_append",
                todo_id=tid,
                text="new stuff",
                project_name="test-proj",
            )
        )
        assert result["result"] == "appended"
        assert result["notes_length"] == len("existing notes\nnew stuff")
        todo_raw = json.loads(
            await call_tool(mcp_app, "todo_get", todo_id=tid, project_name="test-proj")
        )
        assert todo_raw["notes"] == "existing notes\nnew stuff"

    @pytest.mark.anyio()
    async def test_append_to_empty_notes(self, cfg: Any, tmp_path: Any, mcp_app: Any) -> None:
        setup_project(cfg, "test-proj", str(tmp_path / "repo"))
        state.set_session_active("test-proj")
        raw = json.loads(await call_tool(mcp_app, "todo_add", title="T1", project_name="test-proj"))
        tid = raw["todo_id"]
        result = json.loads(
            await call_tool(
                mcp_app,
                "todo_notes_append",
                todo_id=tid,
                text="first note",
                project_name="test-proj",
            )
        )
        assert result["result"] == "appended"
        assert result["notes_length"] == len("first note")
        todo_raw = json.loads(
            await call_tool(mcp_app, "todo_get", todo_id=tid, project_name="test-proj")
        )
        assert todo_raw["notes"] == "first note"
