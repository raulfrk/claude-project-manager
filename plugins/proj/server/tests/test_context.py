"""Tests for the proj_session_context tool in context.py.

Covers:
- Valid config + active project returns full JSON with config, project, integrations keys
- No config returns error message
- Config exists but no active project returns error message
- include_todo_count=False omits count
- include_todo_count=True includes correct count
- Todoist enabled populates integrations correctly
- Trello fields populated from project meta
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectMeta,
    RepoEntry,
    Todo,
)
from tests.conftest import call_tool, setup_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _setup_project_with_todos(
    cfg: ProjConfig,
    name: str,
    tmp_path: Path,
    *,
    todos: list[Todo] | None = None,
    todoist_project_id: str | None = None,
    trello_card_id: str | None = None,
    description: str = "A test project",
    tags: list[str] | None = None,
) -> None:
    """Create a project with optional todos and integration fields."""
    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / name
    proj_dir.mkdir(parents=True, exist_ok=True)

    repo_path = str(tmp_path / "repo")
    Path(repo_path).mkdir(parents=True, exist_ok=True)

    meta = ProjectMeta(
        name=name,
        description=description,
        repos=[RepoEntry(label="code", path=repo_path)],
        dates=ProjectDates(created=today, last_updated=today),
        todoist_project_id=todoist_project_id,
        trello_card_id=trello_card_id,
        tags=tags or [],
    )
    storage.save_meta(cfg, meta)

    index = storage.load_index(cfg)
    index.projects[name] = ProjectEntry(
        name=name, tracking_dir=str(proj_dir), created=today
    )
    storage.save_index(cfg, index)

    # Write todos
    if todos:
        todo_dicts = [t.to_dict() for t in todos]
    else:
        todo_dicts = []
    (proj_dir / "todos.yaml").write_text(
        "todos:\n" + "".join(f"  - {json.dumps(td)}\n" for td in todo_dicts)
        if todo_dicts
        else "todos: []\n"
    )
    (proj_dir / "NOTES.md").write_text(f"# {name}\n")


def _make_todos() -> list[Todo]:
    """Create a set of todos with various statuses for count testing."""
    return [
        Todo(id="T001", title="Task one", status="pending"),
        Todo(id="T002", title="Task two", status="in_progress"),
        Todo(id="T003", title="Task three", status="done"),
        Todo(id="T004", title="Task four", status="pending"),
        Todo(id="T005", title="Task five", status="cancelled"),
        Todo(id="T006", title="Task six", status="in_progress"),
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProjSessionContext:
    """Tests for the proj_session_context MCP tool."""

    async def test_valid_config_and_active_project_returns_full_json(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Valid config + active project returns JSON with config, project, integrations keys."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_session_context")
        data = json.loads(result)

        assert "config" in data
        assert "project" in data
        assert "integrations" in data

        # Verify config section
        assert data["config"]["tracking_dir"] == cfg.tracking_dir
        assert data["config"]["default_priority"] == "medium"

        # Verify project section
        assert data["project"]["name"] == "myapp"
        assert data["project"]["status"] == "active"
        assert data["project"]["priority"] == "medium"
        assert data["project"]["description"] == "A test project"

        # Verify integrations section has expected keys
        assert "todoist" in data["integrations"]
        assert "trello" in data["integrations"]
        assert "jira" in data["integrations"]
        assert "worktree" in data["integrations"]
        assert "zoxide" in data["integrations"]

    async def test_no_config_returns_error(
        self, mcp_app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """No config file returns error string, not JSON."""
        monkeypatch.setattr(
            storage, "_DEFAULT_CONFIG_PATH", tmp_path / "nonexistent.yaml"
        )
        monkeypatch.delenv("PROJ_CONFIG", raising=False)

        result = await call_tool(mcp_app, "proj_session_context")
        assert "No config" in result

    async def test_config_exists_but_no_active_project_returns_error(
        self, mcp_app: Any, cfg: ProjConfig
    ) -> None:
        """Config exists but no active project returns error string."""
        state.clear_session_active()

        result = await call_tool(mcp_app, "proj_session_context")
        assert "No active project" in result

    async def test_include_todo_count_false_omits_count(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """include_todo_count=False (default) omits the todo_count key."""
        _setup_project_with_todos(cfg, "myapp", tmp_path, todos=_make_todos())
        state.set_session_active("myapp")

        result = await call_tool(
            mcp_app, "proj_session_context", include_todo_count=False
        )
        data = json.loads(result)

        assert "todo_count" not in data

    async def test_include_todo_count_true_includes_correct_count(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """include_todo_count=True includes correct counts by status."""
        todos = _make_todos()
        _setup_project_with_todos(cfg, "myapp", tmp_path, todos=todos)
        state.set_session_active("myapp")

        result = await call_tool(
            mcp_app, "proj_session_context", include_todo_count=True
        )
        data = json.loads(result)

        assert "todo_count" in data
        counts = data["todo_count"]
        # Total: 6 (T001-T006)
        assert counts["total"] == 6
        # Open: 4 (pending: T001, T004; in_progress: T002, T006)
        # (done: T003 and cancelled: T005 are excluded)
        assert counts["open"] == 4
        # In progress: 2 (T002, T006)
        assert counts["in_progress"] == 2
        # Pending: 2 (T001, T004)
        assert counts["pending"] == 2

    async def test_todoist_enabled_populates_integrations(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Todoist enabled in config populates integrations.todoist correctly."""
        # Enable todoist in config
        cfg.todoist.enabled = True
        cfg.todoist.mcp_server = "my_todoist_server"
        storage.save_config(cfg)

        _setup_project_with_todos(
            cfg, "myapp", tmp_path, todoist_project_id="12345"
        )
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_session_context")
        data = json.loads(result)

        todoist = data["integrations"]["todoist"]
        assert todoist["enabled"] is True
        assert todoist["mcp_server"] == "my_todoist_server"
        assert todoist["project_id"] == "12345"

    async def test_trello_fields_populated_from_project_meta(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Trello card_id from project meta and enabled from config appear in integrations."""
        # Enable trello in config
        cfg.trello.enabled = True
        storage.save_config(cfg)

        _setup_project_with_todos(
            cfg, "myapp", tmp_path, trello_card_id="abc123"
        )
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_session_context")
        data = json.loads(result)

        trello = data["integrations"]["trello"]
        assert trello["enabled"] is True
        assert trello["card_id"] == "abc123"

        # Also verify the project-level trello_card_id
        assert data["project"]["trello_card_id"] == "abc123"


# ---------------------------------------------------------------------------
# proj_status_context tests
# ---------------------------------------------------------------------------


def _make_status_todos() -> list[Todo]:
    """Create todos with varied statuses, blockers, and children for status context testing."""
    return [
        Todo(id="T001", title="Pending ready", status="pending", priority="high", tags=["backend"]),
        Todo(id="T002", title="In progress task", status="in_progress", priority="medium", children=["T002.1"]),
        Todo(id="T003", title="Done task", status="done", priority="low"),
        Todo(id="T004", title="Blocked task", status="pending", priority="medium", blocked_by=["T002"]),
        Todo(id="T005", title="Cancelled task", status="cancelled"),
        Todo(id="T006", title="Another in progress", status="in_progress", priority="high", tags=["urgent"]),
    ]


@pytest.mark.asyncio
class TestProjStatusContext:
    """Tests for the proj_status_context MCP tool."""

    async def test_returns_full_json_structure(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Active project returns JSON with config, project, todos, git_activity keys."""
        _setup_project_with_todos(cfg, "myapp", tmp_path, todos=_make_status_todos())
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_status_context")
        data = json.loads(result)

        assert "config" in data
        assert "project" in data
        assert "todos" in data
        assert "git_activity" in data

    async def test_config_section(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Config section contains tracking_dir and projects_base_dir."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_status_context")
        data = json.loads(result)

        assert data["config"]["tracking_dir"] == cfg.tracking_dir
        assert data["config"]["projects_base_dir"] == cfg.projects_base_dir

    async def test_project_section_includes_dates(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Project section contains name, status, priority, description, repos, tags, dates."""
        _setup_project_with_todos(
            cfg, "myapp", tmp_path, description="Status test", tags=["web"]
        )
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_status_context")
        data = json.loads(result)

        proj = data["project"]
        assert proj["name"] == "myapp"
        assert proj["status"] == "active"
        assert proj["priority"] == "medium"
        assert proj["description"] == "Status test"
        assert proj["tags"] == ["web"]
        assert "dates" in proj
        assert "created" in proj["dates"]
        assert "last_updated" in proj["dates"]

    async def test_todo_categorisation(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Todos are correctly categorised into in_progress, ready, blocked, all_open, done_count."""
        _setup_project_with_todos(cfg, "myapp", tmp_path, todos=_make_status_todos())
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_status_context")
        data = json.loads(result)
        todos = data["todos"]

        # in_progress: T002, T006
        assert len(todos["in_progress"]) == 2
        ip_ids = {t["id"] for t in todos["in_progress"]}
        assert ip_ids == {"T002", "T006"}

        # ready: pending + not blocked + not in_progress => T001
        assert len(todos["ready"]) == 1
        assert todos["ready"][0]["id"] == "T001"

        # blocked: open + has blocked_by => T004
        assert len(todos["blocked"]) == 1
        assert todos["blocked"][0]["id"] == "T004"
        assert todos["blocked"][0]["blocked_by"] == ["T002"]

        # all_open: not done/cancelled => T001, T002, T004, T006
        assert len(todos["all_open"]) == 4
        open_ids = {t["id"] for t in todos["all_open"]}
        assert open_ids == {"T001", "T002", "T004", "T006"}

        # done_count: T003
        assert todos["done_count"] == 1

    async def test_todo_summary_fields(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Each todo in the lists has id, title, priority, status, tags, blocked_by, children_count."""
        _setup_project_with_todos(cfg, "myapp", tmp_path, todos=_make_status_todos())
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_status_context")
        data = json.loads(result)

        # Check T002 (in_progress, has children)
        t002 = next(t for t in data["todos"]["in_progress"] if t["id"] == "T002")
        assert t002["title"] == "In progress task"
        assert t002["priority"] == "medium"
        assert t002["status"] == "in_progress"
        assert t002["tags"] == []
        assert t002["blocked_by"] == []
        assert t002["children_count"] == 1

        # Check T001 (ready, has tags)
        t001 = data["todos"]["ready"][0]
        assert t001["tags"] == ["backend"]
        assert t001["children_count"] == 0

    async def test_no_active_project_returns_error(
        self, mcp_app: Any, cfg: ProjConfig
    ) -> None:
        """No active project returns error string."""
        state.clear_session_active()

        result = await call_tool(mcp_app, "proj_status_context")
        assert "No active project" in result

    async def test_explicit_project_name(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Passing project_name explicitly resolves the correct project."""
        _setup_project_with_todos(cfg, "other", tmp_path, todos=[
            Todo(id="T001", title="Only task", status="pending"),
        ])

        result = await call_tool(mcp_app, "proj_status_context", project_name="other")
        data = json.loads(result)

        assert data["project"]["name"] == "other"
        assert len(data["todos"]["ready"]) == 1
        assert data["todos"]["done_count"] == 0

    async def test_git_disabled_returns_git_enabled_false(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """When git_enabled is False on the project, git_activity shows git_enabled=False."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        state.set_session_active("myapp")

        # Disable git on the project meta
        meta = storage.load_meta(cfg, "myapp")
        meta.git_enabled = False
        storage.save_meta(cfg, meta)

        result = await call_tool(mcp_app, "proj_status_context")
        data = json.loads(result)

        assert data["git_activity"]["git_enabled"] is False
        assert data["git_activity"]["commits"] == []
        assert data["git_activity"]["branches"] == []

    async def test_empty_todos_returns_empty_lists(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Project with no todos returns empty category lists and done_count=0."""
        _setup_project_with_todos(cfg, "myapp", tmp_path, todos=[])
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_status_context")
        data = json.loads(result)

        assert data["todos"]["in_progress"] == []
        assert data["todos"]["ready"] == []
        assert data["todos"]["blocked"] == []
        assert data["todos"]["all_open"] == []
        assert data["todos"]["done_count"] == 0
