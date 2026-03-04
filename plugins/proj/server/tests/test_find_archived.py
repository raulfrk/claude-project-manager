"""Tests for proj_find_archived_by_title MCP tool."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import ProjConfig, Todo
from tests.conftest import call_tool, setup_project


@pytest.fixture()
def project(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
    setup_project(cfg, "myapp", str(tmp_path))
    state.set_session_active("myapp")
    return cfg, "myapp"


def _write_archive(cfg: ProjConfig, project_name: str, todos: list[Todo]) -> None:
    """Helper to write todos directly to archive.yaml."""
    storage.save_archived_todos(cfg, project_name, todos)


def _make_todo(todo_id: str, title: str) -> Todo:
    return Todo(id=todo_id, title=title, status="done")


@pytest.mark.asyncio
class TestFindArchivedByTitle:
    async def test_exact_match_case_insensitive(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = project
        _write_archive(cfg, name, [_make_todo("1", "Fix race condition in write_yaml")])

        result = await call_tool(
            mcp_app, "proj_find_archived_by_title", title="fix race condition in write_yaml"
        )
        data = json.loads(result)

        assert data["exact_match"] is not None
        assert data["exact_match"]["id"] == "1"
        assert data["exact_match"]["title"] == "Fix race condition in write_yaml"
        assert data["fuzzy_matches"] == []
        assert data["count"] == 1

    async def test_fuzzy_match_above_threshold(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = project
        _write_archive(cfg, name, [_make_todo("2", "Fix race condition in write_yaml")])

        # Similar enough title (ratio >= 0.7) but not exact
        result = await call_tool(
            mcp_app,
            "proj_find_archived_by_title",
            title="Fix race condition in write_yml",
        )
        data = json.loads(result)

        assert data["exact_match"] is None
        assert len(data["fuzzy_matches"]) > 0
        assert data["fuzzy_matches"][0]["id"] == "2"
        assert data["fuzzy_matches"][0]["ratio"] >= 0.7
        assert data["count"] == len(data["fuzzy_matches"])

    async def test_title_below_threshold_returns_empty(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = project
        _write_archive(cfg, name, [_make_todo("3", "Fix race condition in write_yaml")])

        # Completely different title — ratio should be well below 0.7
        result = await call_tool(
            mcp_app,
            "proj_find_archived_by_title",
            title="Deploy frontend container image",
        )
        data = json.loads(result)

        assert data["exact_match"] is None
        assert data["fuzzy_matches"] == []
        assert data["count"] == 0

    async def test_empty_archive_returns_empty(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        # archive.yaml has no todos (created by setup_project with todos.yaml only)
        result = await call_tool(
            mcp_app, "proj_find_archived_by_title", title="Anything"
        )
        data = json.loads(result)

        assert data == {"exact_match": None, "fuzzy_matches": [], "count": 0}

    async def test_missing_archive_file_returns_empty(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = project
        archive = storage.archive_path(cfg, name)
        # Ensure the file does not exist
        if archive.exists():
            archive.unlink()

        result = await call_tool(
            mcp_app, "proj_find_archived_by_title", title="Some title"
        )
        data = json.loads(result)

        assert data == {"exact_match": None, "fuzzy_matches": [], "count": 0}

    async def test_multiple_fuzzy_matches_sorted_by_ratio_descending(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = project
        _write_archive(
            cfg,
            name,
            [
                _make_todo("10", "Refactor storage module"),
                _make_todo("11", "Refactor storage layer"),
                _make_todo("12", "Refactor storage helpers"),
            ],
        )

        result = await call_tool(
            mcp_app,
            "proj_find_archived_by_title",
            title="Refactor storage module code",
        )
        data = json.loads(result)

        assert data["exact_match"] is None
        assert len(data["fuzzy_matches"]) >= 2
        ratios = [m["ratio"] for m in data["fuzzy_matches"]]
        # Must be sorted descending
        assert ratios == sorted(ratios, reverse=True)
        # All returned matches must meet the default threshold
        assert all(r >= 0.7 for r in ratios)
        assert data["count"] == len(data["fuzzy_matches"])
