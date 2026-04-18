"""Tests for the proj_session_context tool in context.py.

Covers:
- Valid config + active project returns full JSON with config, project, integrations keys
- No config returns error message
- Config exists but no active project returns error message
- include_todo_count=False omits count
- include_todo_count=True includes correct count
- Todoist enabled populates integrations correctly
- Trello fields populated from project meta
- _read_session_history with mock session files
- _read_session_history with no sessions directory
- _read_session_history with malformed session files
- _build_context includes session history section
- _build_context compact mode excludes session history
- Backward compatibility: project without sessions/ dir
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
from server.tools.context import _build_context, _read_project_knowledge, _read_session_history
from tests.conftest import call_tool

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
    index.projects[name] = ProjectEntry(name=name, tracking_dir=str(proj_dir), created=today)
    storage.save_index(cfg, index)

    # Write todos via SQLite (direct YAML write bypassed after migration)
    storage.save_todos(cfg, name, todos or [])
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
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", tmp_path / "nonexistent.yaml")
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

        result = await call_tool(mcp_app, "proj_session_context", include_todo_count=False)
        data = json.loads(result)

        assert "todo_count" not in data

    async def test_include_todo_count_true_includes_correct_count(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """include_todo_count=True includes correct counts by status."""
        todos = _make_todos()
        _setup_project_with_todos(cfg, "myapp", tmp_path, todos=todos)
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_session_context", include_todo_count=True)
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

        _setup_project_with_todos(cfg, "myapp", tmp_path, todoist_project_id="12345")
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

        _setup_project_with_todos(cfg, "myapp", tmp_path, trello_card_id="abc123")
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_session_context")
        data = json.loads(result)

        trello = data["integrations"]["trello"]
        assert trello["enabled"] is True
        assert trello["card_id"] == "abc123"

        # Also verify the project-level trello_card_id
        assert data["project"]["trello_card_id"] == "abc123"

    async def test_session_context_exposes_trello_label_names_defaults(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Trello label names default to 'proj' / 'proj-task' when absent."""
        cfg.trello.enabled = True
        storage.save_config(cfg)

        _setup_project_with_todos(cfg, "myapp", tmp_path)
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_session_context")
        data = json.loads(result)

        trello = data["integrations"]["trello"]
        assert trello["proj_label_name"] == "proj"
        assert trello["proj_task_label_name"] == "proj-task"

    async def test_session_context_exposes_trello_label_names_custom(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Custom trello label names surface on the session_context dict."""
        cfg.trello.enabled = True
        cfg.trello.proj_label_name = "cpm"
        cfg.trello.proj_task_label_name = "cpm-task"
        storage.save_config(cfg)

        _setup_project_with_todos(cfg, "myapp", tmp_path)
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_session_context")
        data = json.loads(result)

        trello = data["integrations"]["trello"]
        assert trello["proj_label_name"] == "cpm"
        assert trello["proj_task_label_name"] == "cpm-task"

    async def test_session_context_surfaces_empty_label_name(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Empty string in proj.yaml surfaces as empty (not defaulted)."""
        cfg.trello.enabled = True
        cfg.trello.proj_label_name = ""
        cfg.trello.proj_task_label_name = ""
        storage.save_config(cfg)

        _setup_project_with_todos(cfg, "myapp", tmp_path)
        state.set_session_active("myapp")

        result = await call_tool(mcp_app, "proj_session_context")
        data = json.loads(result)

        trello = data["integrations"]["trello"]
        assert trello["proj_label_name"] == ""
        assert trello["proj_task_label_name"] == ""


# ---------------------------------------------------------------------------
# proj_status_context tests
# ---------------------------------------------------------------------------


def _make_status_todos() -> list[Todo]:
    """Create todos with varied statuses, blockers, and children for status context testing."""
    return [
        Todo(id="T001", title="Pending ready", status="pending", priority="high", tags=["backend"]),
        Todo(
            id="T002",
            title="In progress task",
            status="in_progress",
            priority="medium",
            # Flat model: children are identified by group:<id> tags on the child todo.
            # children_count for T002 is computed dynamically from all todos at query time.
        ),
        Todo(id="T003", title="Done task", status="done", priority="low"),
        Todo(
            id="T004",
            title="Blocked task",
            status="pending",
            priority="medium",
            blocked_by=["T002"],
        ),
        Todo(id="T005", title="Cancelled task", status="cancelled"),
        Todo(
            id="T006",
            title="Another in progress",
            status="in_progress",
            priority="high",
            tags=["urgent"],
        ),
        Todo(
            id="T002.1",
            title="Child of T002",
            status="done",
            priority="low",
            tags=["group:T002"],
        ),
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

    async def test_project_section_includes_dates(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Project section contains name, status, priority, description, repos, tags, dates."""
        _setup_project_with_todos(cfg, "myapp", tmp_path, description="Status test", tags=["web"])
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

    async def test_todo_categorisation(self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path) -> None:
        """Todos are correctly categorised into in_progress,
        ready, blocked, all_open, done_count."""
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

        # done_count: T003 + T002.1 (child of T002)
        assert todos["done_count"] == 2

    async def test_todo_summary_fields(self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path) -> None:
        """Each todo in the lists has id, title, priority,
        status, tags, blocked_by, children_count."""
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

    async def test_no_active_project_returns_error(self, mcp_app: Any, cfg: ProjConfig) -> None:
        """No active project returns error string."""
        state.clear_session_active()

        result = await call_tool(mcp_app, "proj_status_context")
        assert "No active project" in result

    async def test_explicit_project_name(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Passing project_name explicitly resolves the correct project."""
        _setup_project_with_todos(
            cfg,
            "other",
            tmp_path,
            todos=[
                Todo(id="T001", title="Only task", status="pending"),
            ],
        )

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


# ---------------------------------------------------------------------------
# Session history tests
# ---------------------------------------------------------------------------

SESSION_A = """\
# Session: 2026-03-20

## Key Decisions
- Adopted new caching strategy for API calls
- Switched from REST to GraphQL for data layer

## Todos Worked On
- T100 caching work

## Open Questions
- Should we add rate limiting to the cache layer?
- Is GraphQL overkill for simple CRUD?
"""

SESSION_B = """\
# Session: 2026-03-21

## Key Decisions
- Added rate limiting middleware
- Adopted new caching strategy for API calls

## Insights Discovered
- GraphQL reduces payload size by 40%

## Open Questions
- How to handle cache invalidation on deploy?
"""

SESSION_C = """\
# Session: 2026-03-22

## Key Decisions
- Finalized deploy pipeline with blue-green strategy

## Open Questions
- Need to benchmark cold-start times
"""


def _create_sessions(cfg: ProjConfig, project_name: str, files: dict[str, str]) -> None:
    """Write session files into the project's sessions dir."""
    sessions_dir = Path(cfg.tracking_dir) / project_name / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in files.items():
        (sessions_dir / filename).write_text(content)


class TestReadSessionHistory:
    """Tests for _read_session_history helper."""

    def test_with_session_files(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Returns summary, decisions, and questions from session files."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        _create_sessions(
            cfg,
            "myapp",
            {
                "session-2026-03-20.md": SESSION_A,
                "session-2026-03-21.md": SESSION_B,
                "session-2026-03-22.md": SESSION_C,
            },
        )

        result = _read_session_history(cfg, "myapp")

        # Summary from latest session (SESSION_C), after header
        assert "summary" in result
        summary = result["summary"]
        assert isinstance(summary, str)
        assert "Finalized deploy pipeline" in summary
        assert len(summary) <= 300

        # Decisions: last 5 across sessions (most recent first), deduplicated
        decisions = result["decisions"]
        assert isinstance(decisions, list)
        assert len(decisions) <= 5
        # Most recent session's decision first
        assert decisions[0] == "Finalized deploy pipeline with blue-green strategy"
        # Duplicate "Adopted new caching strategy" should appear only once
        caching_count = sum(1 for d in decisions if "caching strategy" in d)
        assert caching_count == 1

    def test_no_sessions_directory(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Returns empty dict when sessions/ directory does not exist."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        # No sessions dir created
        result = _read_session_history(cfg, "myapp")
        assert result == {}

    def test_empty_sessions_directory(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Returns empty dict when sessions/ exists but has no session files."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        sessions_dir = Path(cfg.tracking_dir) / "myapp" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)

        result = _read_session_history(cfg, "myapp")
        assert result == {}

    def test_malformed_session_files(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Gracefully handles session files without expected sections."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        _create_sessions(
            cfg,
            "myapp",
            {
                "session-2026-03-20.md": "Just some random text\nNo sections here.",
                "session-2026-03-21.md": "# Session: 2026-03-21\n\nSome notes but no ## sections.",
            },
        )

        result = _read_session_history(cfg, "myapp")

        # Should still return a result with summary
        assert "summary" in result
        summary = result["summary"]
        assert isinstance(summary, str)
        # Decisions and questions should be empty lists
        assert result["decisions"] == []
        assert result["questions"] == []

    def test_questions_from_last_3_sessions(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Questions are collected from the last 3 sessions only."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        old_session = """\
# Session: 2026-03-10

## Open Questions
- This old question should NOT appear
"""
        _create_sessions(
            cfg,
            "myapp",
            {
                "session-2026-03-10.md": old_session,
                "session-2026-03-20.md": SESSION_A,
                "session-2026-03-21.md": SESSION_B,
                "session-2026-03-22.md": SESSION_C,
            },
        )

        result = _read_session_history(cfg, "myapp")
        questions = result["questions"]

        # Old question from session-2026-03-10 should NOT be included
        assert not any("old question" in q.lower() for q in questions)
        # Questions from A, B, C should be present
        assert any("rate limiting" in q for q in questions)
        assert any("cache invalidation" in q for q in questions)
        assert any("cold-start" in q for q in questions)

    def test_decisions_deduplicated(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Duplicate decisions across sessions are deduplicated."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        _create_sessions(
            cfg,
            "myapp",
            {
                "session-2026-03-20.md": SESSION_A,
                "session-2026-03-21.md": SESSION_B,
            },
        )

        result = _read_session_history(cfg, "myapp")
        decisions = result["decisions"]

        # "Adopted new caching strategy for API calls" appears in both A and B
        caching_decisions = [d for d in decisions if "caching strategy" in d]
        assert len(caching_decisions) == 1


class TestBuildContextSessionHistory:
    """Tests for session history integration in _build_context."""

    def test_includes_session_history(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """_build_context includes session history sections when not compact."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        _create_sessions(
            cfg,
            "myapp",
            {
                "session-2026-03-22.md": SESSION_C,
            },
        )

        result = _build_context(cfg, "myapp", compact=False)

        assert "### Last Session" in result
        assert "### Key Decisions" in result
        assert "Finalized deploy pipeline" in result
        assert "### Open Questions" in result
        assert "- [ ] Need to benchmark cold-start times" in result

    def test_compact_excludes_session_history(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """_build_context in compact mode does NOT include session history."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        _create_sessions(
            cfg,
            "myapp",
            {
                "session-2026-03-22.md": SESSION_C,
            },
        )

        result = _build_context(cfg, "myapp", compact=True)

        assert "### Last Session" not in result
        assert "### Key Decisions" not in result
        assert "### Open Questions" not in result

    def test_backward_compatible_no_sessions(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """_build_context works normally for projects without sessions/ dir."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        # No sessions dir created

        result = _build_context(cfg, "myapp", compact=False)

        # Should produce valid context without session sections
        assert "## Active Project: myapp" in result
        assert "### Last Session" not in result
        assert "### Key Decisions" not in result


# ---------------------------------------------------------------------------
# Project knowledge tests
# ---------------------------------------------------------------------------

KNOWLEDGE_SINGLE_SECTION = """\
## 2026-03-25
- Adopted caching strategy for API calls
- Switched from REST to GraphQL
- Added rate limiting middleware
"""

KNOWLEDGE_MULTI_SECTION = """\
## 2026-03-20
- Old decision that should not appear
- Another old decision

## 2026-03-25
- Recent decision one
- Recent decision two
- Recent decision three
- Recent decision four
- Recent decision five
- Recent decision six (should be truncated)
"""


def _write_knowledge(cfg: ProjConfig, project_name: str, content: str) -> None:
    """Write knowledge.md into the project's tracking dir."""
    knowledge_path = Path(cfg.tracking_dir) / project_name / "knowledge.md"
    knowledge_path.parent.mkdir(parents=True, exist_ok=True)
    knowledge_path.write_text(content)


class TestReadProjectKnowledge:
    """Tests for _read_project_knowledge helper."""

    def test_returns_bullets_from_single_section(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Returns bullet entries from a single-section knowledge.md."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        _write_knowledge(cfg, "myapp", KNOWLEDGE_SINGLE_SECTION)

        result = _read_project_knowledge(cfg, "myapp")

        assert len(result) == 3
        assert result[0] == "Adopted caching strategy for API calls"
        assert result[1] == "Switched from REST to GraphQL"
        assert result[2] == "Added rate limiting middleware"

    def test_returns_only_most_recent_section(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Only returns bullets from the most recent (last) section."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        _write_knowledge(cfg, "myapp", KNOWLEDGE_MULTI_SECTION)

        result = _read_project_knowledge(cfg, "myapp")

        # Should not include old section bullets
        assert not any("Old decision" in b for b in result)
        assert result[0] == "Recent decision one"

    def test_max_5_bullets(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Returns at most 5 bullet entries even if more exist."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        _write_knowledge(cfg, "myapp", KNOWLEDGE_MULTI_SECTION)

        result = _read_project_knowledge(cfg, "myapp")

        assert len(result) == 5
        assert not any("truncated" in b for b in result)

    def test_no_knowledge_file(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Returns empty list when knowledge.md does not exist."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)

        result = _read_project_knowledge(cfg, "myapp")

        assert result == []

    def test_empty_knowledge_file(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Returns empty list when knowledge.md exists but has no sections."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        _write_knowledge(cfg, "myapp", "# Knowledge\nSome preamble text.\n")

        result = _read_project_knowledge(cfg, "myapp")

        assert result == []


class TestBuildContextKnowledge:
    """Tests for project knowledge integration in _build_context."""

    def test_includes_knowledge_section(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """_build_context includes Project Knowledge section when knowledge.md exists."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        _write_knowledge(cfg, "myapp", KNOWLEDGE_SINGLE_SECTION)

        result = _build_context(cfg, "myapp", compact=False)

        assert "### Project Knowledge" in result
        assert "- Adopted caching strategy for API calls" in result
        assert "- Switched from REST to GraphQL" in result

    def test_compact_excludes_knowledge(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """_build_context in compact mode does NOT include Project Knowledge."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)
        _write_knowledge(cfg, "myapp", KNOWLEDGE_SINGLE_SECTION)

        result = _build_context(cfg, "myapp", compact=True)

        assert "### Project Knowledge" not in result

    def test_no_knowledge_file_no_section(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """_build_context works normally without knowledge.md."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)

        result = _build_context(cfg, "myapp", compact=False)

        assert "## Active Project: myapp" in result
        assert "### Project Knowledge" not in result


class TestBuildContextInjectionEnabled:
    """Tests for _build_context when context_injection is enabled."""

    def test_injection_enabled_uses_inject_context(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """When context_injection.enabled=True, _build_context uses inject_context output."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)

        # Write notes and knowledge for injection to pick up
        notes_path = Path(cfg.tracking_dir) / "myapp" / "NOTES.md"
        notes_path.write_text("## 2026-04-07\nInjected note content here\n")
        _write_knowledge(cfg, "myapp", "## 2026-04-07\n- Injected knowledge bullet\n")

        cfg.context_injection.enabled = True
        cfg.context_injection.budget = 2000
        storage.save_config(cfg)

        result = _build_context(cfg, "myapp", compact=False)

        # Should contain injected content (via context_injection path)
        assert "## Active Project: myapp" in result
        # At least one injected section should appear
        assert (
            "Recent Notes" in result or "Project Knowledge" in result or "Key Decisions" in result
        )

    def test_injection_enabled_compact_still_skips(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Compact mode skips context injection even when enabled."""
        _setup_project_with_todos(cfg, "myapp", tmp_path)

        notes_path = Path(cfg.tracking_dir) / "myapp" / "NOTES.md"
        notes_path.write_text("## 2026-04-07\nSome note\n")

        cfg.context_injection.enabled = True
        cfg.context_injection.budget = 2000
        storage.save_config(cfg)

        result = _build_context(cfg, "myapp", compact=True)

        assert "## Active Project: myapp" in result
        assert "### Recent Notes" not in result
        assert "### Key Decisions" not in result
        assert "### Project Knowledge" not in result


# ---------------------------------------------------------------------------
# Sockets cleanup
# ---------------------------------------------------------------------------


class TestSocketsCleanupStale:
    """Tests for sockets_cleanup_stale helper and its ctx_session_start wiring."""

    def _write_installed(self, path: Path, plugins: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"plugins": plugins}))

    def test_stale_hooks_removed_router_live(self, tmp_path: Path) -> None:
        from server.lib.sockets_cleanup import sockets_cleanup_stale

        sockets = tmp_path / "sockets"
        sockets.mkdir()
        stale = sockets / "hooks"
        stale.write_text("")
        installed = tmp_path / "installed_plugins.json"
        self._write_installed(installed, {"router@claude-project-manager": {}})

        removed = sockets_cleanup_stale(sockets, installed)

        assert removed == ["hooks"]
        assert not stale.exists()

    def test_stale_perms_removed_sandbox_live(self, tmp_path: Path) -> None:
        from server.lib.sockets_cleanup import sockets_cleanup_stale

        sockets = tmp_path / "sockets"
        sockets.mkdir()
        stale = sockets / "perms"
        stale.write_text("")
        installed = tmp_path / "installed_plugins.json"
        self._write_installed(installed, {"sandbox@claude-project-manager": {}})

        removed = sockets_cleanup_stale(sockets, installed)

        assert removed == ["perms"]
        assert not stale.exists()

    def test_missing_sockets_dir_returns_empty(self, tmp_path: Path) -> None:
        from server.lib.sockets_cleanup import sockets_cleanup_stale

        installed = tmp_path / "installed_plugins.json"
        self._write_installed(installed, {"router@claude-project-manager": {}})

        removed = sockets_cleanup_stale(tmp_path / "nope", installed)

        assert removed == []

    def test_missing_installed_json_returns_empty(self, tmp_path: Path) -> None:
        from server.lib.sockets_cleanup import sockets_cleanup_stale

        sockets = tmp_path / "sockets"
        sockets.mkdir()
        (sockets / "hooks").write_text("")

        removed = sockets_cleanup_stale(sockets, tmp_path / "absent.json")

        assert removed == []
        assert (sockets / "hooks").exists()

    def test_broken_json_returns_empty(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        import logging

        from server.lib.sockets_cleanup import sockets_cleanup_stale

        sockets = tmp_path / "sockets"
        sockets.mkdir()
        (sockets / "hooks").write_text("")
        installed = tmp_path / "installed_plugins.json"
        installed.write_text("not json")

        with caplog.at_level(logging.WARNING, logger="server.lib.sockets_cleanup"):
            removed = sockets_cleanup_stale(sockets, installed)

        assert removed == []
        assert (sockets / "hooks").exists()
        assert any("could not parse" in rec.message for rec in caplog.records)

    def test_second_call_no_op(self, tmp_path: Path) -> None:
        from server.lib.sockets_cleanup import sockets_cleanup_stale

        sockets = tmp_path / "sockets"
        sockets.mkdir()
        (sockets / "hooks").write_text("")
        (sockets / "custom").write_text("")  # not in allowlist, must be untouched
        installed = tmp_path / "installed_plugins.json"
        self._write_installed(installed, {"router@claude-project-manager": {}})

        first = sockets_cleanup_stale(sockets, installed)
        second = sockets_cleanup_stale(sockets, installed)

        assert first == ["hooks"]
        assert second == []
        assert (sockets / "custom").exists()
        assert not (sockets / "hooks").exists()

    def test_ctx_session_start_regression(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ctx_session_start removes stale socket files and returns context string."""
        from mcp.server.fastmcp import FastMCP

        from server.tools import context as context_module

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        sockets = fake_home / ".claude" / "sockets"
        sockets.mkdir(parents=True)
        stale = sockets / "hooks"
        stale.write_text("")
        installed = fake_home / ".claude" / "plugins" / "installed_plugins.json"
        installed.parent.mkdir(parents=True)
        installed.write_text(json.dumps({"plugins": {"router@claude-project-manager": {}}}))

        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))

        config_path = tmp_path / "proj.yaml"
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
        monkeypatch.delenv("PROJ_CONFIG", raising=False)
        cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
        storage.save_config(cfg)

        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        today = str(date.today())
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True)
        (proj_dir / "todos.yaml").write_text("todos: []\n")
        (proj_dir / "NOTES.md").write_text("# myapp\n")
        meta = ProjectMeta(
            name="myapp",
            repos=[RepoEntry(label="code", path=str(repo_path))],
            dates=ProjectDates(created=today, last_updated=today),
        )
        storage.save_meta(cfg, meta)
        index = storage.load_index(cfg)
        index.projects["myapp"] = ProjectEntry(
            name="myapp", tracking_dir=str(proj_dir), created=today
        )
        storage.save_index(cfg, index)

        app = FastMCP("regression-proj")
        context_module.register(app)

        import asyncio

        async def _invoke() -> str:
            return await call_tool(app, "ctx_session_start", cwd=str(repo_path))

        result = asyncio.run(_invoke())

        assert "## Active Project: myapp" in result
        assert not stale.exists()


# ---------------------------------------------------------------------------
# Hooks status line tests (router health probe integration)
# ---------------------------------------------------------------------------


class TestCtxSessionStartHooksStatus:
    """Tests for the **Hooks** status line appended to ctx_session_start output."""

    def _setup(self, cfg: ProjConfig, tmp_path: Path) -> Path:
        repo = tmp_path / "repo"
        repo.mkdir()
        today = str(date.today())
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True)
        (proj_dir / "todos.yaml").write_text("todos: []\n")
        (proj_dir / "NOTES.md").write_text("# myapp\n")
        meta = ProjectMeta(
            name="myapp",
            repos=[RepoEntry(label="code", path=str(repo))],
            dates=ProjectDates(created=today, last_updated=today),
        )
        storage.save_meta(cfg, meta)
        index = storage.load_index(cfg)
        index.projects["myapp"] = ProjectEntry(
            name="myapp", tracking_dir=str(proj_dir), created=today
        )
        storage.save_index(cfg, index)
        return repo

    def test_ctx_session_start_appends_reachable_line(
        self, cfg: ProjConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reachable router → `**Hooks**: ✓ router reachable` appended."""
        import asyncio

        from mcp.server.fastmcp import FastMCP

        from server.tools import context as context_module

        repo = self._setup(cfg, tmp_path)

        async def _fake(*args: Any, **kwargs: Any) -> tuple[bool, str]:
            return True, ""

        monkeypatch.setattr(context_module, "check_router_reachable", _fake)

        app = FastMCP("hooks-status-ok")
        context_module.register(app)

        async def _invoke() -> str:
            return await call_tool(app, "ctx_session_start", cwd=str(repo))

        result = asyncio.run(_invoke())
        assert "**Hooks**: ✓ router reachable" in result

    def test_ctx_session_start_appends_unreachable_line(
        self, cfg: ProjConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Unreachable router → `**Hooks**: ✗ router unreachable — fix: ...` appended."""
        import asyncio

        from mcp.server.fastmcp import FastMCP

        from server.tools import context as context_module

        repo = self._setup(cfg, tmp_path)

        async def _fake(*args: Any, **kwargs: Any) -> tuple[bool, str]:
            return False, "router socket dead — restart Claude Code"

        monkeypatch.setattr(context_module, "check_router_reachable", _fake)

        app = FastMCP("hooks-status-fail")
        context_module.register(app)

        async def _invoke() -> str:
            return await call_tool(app, "ctx_session_start", cwd=str(repo))

        result = asyncio.run(_invoke())
        assert "**Hooks**: ✗ router unreachable" in result
        assert "router socket dead" in result

    def test_ctx_session_start_degrades_on_helper_crash(
        self, cfg: ProjConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Helper raising → context still returned, no Hooks line."""
        import asyncio

        from mcp.server.fastmcp import FastMCP

        from server.tools import context as context_module

        repo = self._setup(cfg, tmp_path)

        async def _crash(*args: Any, **kwargs: Any) -> tuple[bool, str]:
            raise RuntimeError("probe exploded")

        monkeypatch.setattr(context_module, "check_router_reachable", _crash)

        app = FastMCP("hooks-status-crash")
        context_module.register(app)

        async def _invoke() -> str:
            return await call_tool(app, "ctx_session_start", cwd=str(repo))

        result = asyncio.run(_invoke())
        assert "## Active Project: myapp" in result
        assert "**Hooks**:" not in result


# ---------------------------------------------------------------------------
# Tests for claudemd_refresh_managed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestClaudemdRefreshManaged:
    """Tests for the claudemd_refresh_managed MCP tool."""

    async def test_claudemd_refresh_managed_creates_file(
        self, mcp_app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool creates ~/.claude/CLAUDE.md with managed section when file absent."""
        from claudemd import MANAGED_SECTION, MARKER_END, MARKER_START

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        target = tmp_path / ".claude" / "CLAUDE.md"

        raw = await mcp_app.call_tool("claudemd_refresh_managed", {})
        items = raw[0] if isinstance(raw, tuple) else raw
        result = json.loads(items[0].text)

        assert result == {"updated": True, "path": str(target)}
        assert target.exists()
        content = target.read_text(encoding="utf-8")
        assert MARKER_START in content
        assert MARKER_END in content
        assert MANAGED_SECTION in content

    async def test_claudemd_refresh_managed_noop_when_current(
        self, mcp_app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool returns updated=False when managed section is already current."""
        from claudemd import MANAGED_SECTION

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        target = tmp_path / ".claude" / "CLAUDE.md"
        target.parent.mkdir()
        target.write_text(MANAGED_SECTION + "\n", encoding="utf-8")

        raw = await mcp_app.call_tool("claudemd_refresh_managed", {})
        items = raw[0] if isinstance(raw, tuple) else raw
        result = json.loads(items[0].text)

        assert result == {"updated": False, "path": str(target)}

    async def test_claudemd_refresh_managed_replaces_stale_section(
        self, mcp_app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tool replaces stale managed block while preserving surrounding user content."""
        from claudemd import MANAGED_SECTION, MARKER_END, MARKER_START

        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        target = tmp_path / ".claude" / "CLAUDE.md"
        target.parent.mkdir()
        stale = f"{MARKER_START}\n## Old Rules\n- Stale bullet\n{MARKER_END}"
        target.write_text(f"# User header\n\n{stale}\n\n# User footer\n", encoding="utf-8")

        raw = await mcp_app.call_tool("claudemd_refresh_managed", {})
        items = raw[0] if isinstance(raw, tuple) else raw
        result = json.loads(items[0].text)

        assert result == {"updated": True, "path": str(target)}
        content = target.read_text(encoding="utf-8")
        assert "Stale bullet" not in content
        assert MANAGED_SECTION in content
        assert "# User header" in content
        assert "# User footer" in content
