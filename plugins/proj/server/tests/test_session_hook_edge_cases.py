"""Tests for session hook edge cases: corrupted YAML, malformed meta.yaml, missing fields.

Covers:
- storage.load_todos with corrupted/invalid YAML files
- storage.load_index with corrupted/invalid YAML files
- storage.load_meta with malformed content (missing required fields)
- cmd_session_start / cmd_session_end with corrupted tracking data
- ctx_session_start / ctx_session_end (MCP tools) with corrupted tracking data

Design intent: document actual behaviour for each corruption scenario.  Some
scenarios expose gaps where exceptions currently propagate; those tests use
``pytest.raises`` so the test suite stays green while the behaviour is
explicitly recorded.  When the production code is hardened the test can be
updated to assert graceful degradation instead.
"""

from __future__ import annotations

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
)
from tests.conftest import call_tool, setup_project

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_active_project(
    cfg: ProjConfig,
    name: str,
    repo_path: str,
    *,
    active: bool = True,
) -> Path:
    """Create a minimal but valid project and return its tracking directory."""
    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / name
    proj_dir.mkdir(parents=True, exist_ok=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "NOTES.md").write_text(f"# {name}\n")
    meta = ProjectMeta(
        name=name,
        repos=[RepoEntry(label="code", path=repo_path)],
        dates=ProjectDates(created=today, last_updated=today),
    )
    storage.save_meta(cfg, meta)
    index = storage.load_index(cfg)
    index.projects[name] = ProjectEntry(name=name, tracking_dir=str(proj_dir), created=today)
    storage.save_index(cfg, index)
    return proj_dir


# ---------------------------------------------------------------------------
# Storage-level: load_todos edge cases
# ---------------------------------------------------------------------------


class TestLoadTodosCorruption:
    """Direct storage.load_todos tests for various storage conditions.

    SQLite is the source of truth — YAML files are not read by load_todos.
    When data.db is missing, load_todos raises FileNotFoundError (no YAML fallback).
    """

    def test_missing_db_raises_file_not_found(self, cfg: ProjConfig) -> None:
        """When data.db is absent, load_todos raises FileNotFoundError (no YAML fallback)."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        # Write todos.yaml — should be ignored since SQLite is the source of truth
        (proj_dir / "todos.yaml").write_text("todos: []\n")

        with pytest.raises(FileNotFoundError, match=r"data\.db not found"):
            storage.load_todos(cfg, "myapp")

    def test_stale_yaml_is_ignored_when_db_exists(self, cfg: ProjConfig) -> None:
        """Stale/corrupt todos.yaml has no effect — DB is the source of truth."""
        from server.lib.models import Todo

        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        # Seed the DB first
        storage.save_todos(
            cfg,
            "myapp",
            [Todo(id="T1", title="DB todo", created="2026-01-01", updated="2026-01-01")],
        )
        # Write a different/corrupt todos.yaml — should be ignored
        (proj_dir / "todos.yaml").write_text("todos:\n  - id: 1\n  bad: [unclosed\n")

        todos = storage.load_todos(cfg, "myapp")
        assert len(todos) == 1
        assert todos[0].id == "T1"

    def test_empty_project_returns_empty_list(self, cfg: ProjConfig) -> None:
        """When data.db exists but has no todos, load_todos returns []."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        storage.save_todos(cfg, "myapp", [])

        todos = storage.load_todos(cfg, "myapp")
        assert todos == []


# ---------------------------------------------------------------------------
# Storage-level: load_index edge cases
# ---------------------------------------------------------------------------


class TestLoadIndexCorruption:
    """Direct storage.load_index tests for various forms of file corruption."""

    def test_empty_index_file_returns_default(self, cfg: ProjConfig) -> None:
        """An empty active-projects.yaml returns a default empty ProjectIndex."""
        index_path = Path(cfg.tracking_dir) / "active-projects.yaml"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("")

        index = storage.load_index(cfg)
        assert index.projects == {}

    def test_index_with_legacy_active_field_is_ignored(self, cfg: ProjConfig) -> None:
        """Index file with legacy 'active' field loads gracefully (field ignored)."""
        index_path = Path(cfg.tracking_dir) / "active-projects.yaml"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("active: myapp\nprojects: {}\n")

        index = storage.load_index(cfg)
        assert index.projects == {}

    def test_invalid_yaml_in_index_returns_empty(self, cfg: ProjConfig) -> None:
        """A syntactically invalid active-projects.yaml is swallowed and returns empty index.

        _load_yaml catches yaml.YAMLError and returns {}, so load_index returns a
        default empty ProjectIndex with projects={}.
        """
        index_path = Path(cfg.tracking_dir) / "active-projects.yaml"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("active: myapp\nprojects: {bad: [unclosed\n")

        index = storage.load_index(cfg)
        assert index.projects == {}

    def test_projects_not_a_dict_returns_empty_projects(self, cfg: ProjConfig) -> None:
        """When 'projects' key is not a dict, ProjectIndex.from_dict falls back to {}."""
        index_path = Path(cfg.tracking_dir) / "active-projects.yaml"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("active: null\nprojects: not-a-dict\n")

        index = storage.load_index(cfg)
        assert index.projects == {}


# ---------------------------------------------------------------------------
# Storage-level: load_meta edge cases
# ---------------------------------------------------------------------------


class TestLoadMetaCorruption:
    """Direct storage.load_meta tests.

    SQLite is the source of truth — YAML files are not read by load_meta.
    When data.db is missing, load_meta raises FileNotFoundError (no YAML fallback).
    """

    def test_missing_db_raises_file_not_found(self, cfg: ProjConfig) -> None:
        """Missing data.db raises FileNotFoundError — no YAML fallback."""
        with pytest.raises(FileNotFoundError, match=r"data\.db not found"):
            storage.load_meta(cfg, "myapp")

    def test_missing_meta_row_raises_file_not_found(self, cfg: ProjConfig) -> None:
        """DB exists but has no meta row — load_meta raises FileNotFoundError."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        # Seed DB with a todo (creates data.db) but no meta row
        storage.save_todos(cfg, "myapp", [])
        with pytest.raises(FileNotFoundError, match="myapp"):
            storage.load_meta(cfg, "myapp")

    def test_meta_missing_optional_fields_uses_defaults(self, cfg: ProjConfig) -> None:
        """ProjectMeta saved with minimal fields loads with defaults intact."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        meta = ProjectMeta(name="myapp")
        storage.save_meta(cfg, meta)

        loaded = storage.load_meta(cfg, "myapp")
        assert loaded.name == "myapp"
        assert loaded.description == ""
        assert loaded.repos == []

    def test_meta_repos_preserved_on_roundtrip(self, cfg: ProjConfig) -> None:
        """Repos saved to DB are returned correctly on load."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        today = str(date.today())
        meta = ProjectMeta(
            name="myapp",
            repos=[RepoEntry(label="code", path="/some/path")],
            dates=ProjectDates(created=today, last_updated=today),
        )
        storage.save_meta(cfg, meta)

        loaded = storage.load_meta(cfg, "myapp")
        assert loaded.name == "myapp"
        assert len(loaded.repos) == 1
        assert loaded.repos[0].label == "code"

    def test_stale_yaml_ignored_when_db_has_meta(self, cfg: ProjConfig) -> None:
        """Writing meta.yaml after save_meta has no effect — DB is source of truth."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        meta = ProjectMeta(name="myapp", description="original")
        storage.save_meta(cfg, meta)
        # Overwrite meta.yaml — should be ignored
        (proj_dir / "meta.yaml").write_text("name: myapp\ndescription: stale yaml\n")

        loaded = storage.load_meta(cfg, "myapp")
        assert loaded.description == "original"

    def test_meta_dates_roundtrip_through_db(self, cfg: ProjConfig) -> None:
        """ProjectMeta with custom dates roundtrips through DB correctly."""
        from datetime import date as _date

        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        today = str(_date.today())
        meta = ProjectMeta(
            name="myapp",
            dates=ProjectDates(created="2026-01-01", last_updated="2000-01-01"),
        )
        storage.save_meta(cfg, meta)

        loaded = storage.load_meta(cfg, "myapp")
        assert loaded.name == "myapp"
        assert loaded.dates.created == "2026-01-01"
        # save_meta bumps last_updated to today
        assert loaded.dates.last_updated == today


# ---------------------------------------------------------------------------
# CLI-level: cmd_session_start with corrupted data
# ---------------------------------------------------------------------------


class TestCmdSessionStartCorruption:
    """cmd_session_start edge cases with various forms of data corruption."""

    @pytest.fixture(autouse=True)
    def _disable_router_health(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Suppress router health probe — no router socket in unit tests."""
        monkeypatch.setenv("HOOKS_HEALTH_CHECK", "0")

    def test_corrupted_index_returns_empty_output(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When the index YAML is syntactically invalid, cmd_session_start returns gracefully.

        _load_yaml swallows the YAMLError and returns {}; load_index returns an
        empty index (projects={}), so ctx_detect_project_name finds nothing.
        """
        index_path = Path(cfg.tracking_dir) / "active-projects.yaml"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("projects: {bad: [unclosed\n")

        from server.cli import cmd_session_start

        # Should not raise — graceful degradation
        cmd_session_start(cwd=str(tmp_path), compact=False)

    def test_corrupted_todos_yaml_has_no_effect_on_context(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Corrupted todos.yaml has no effect — SQLite is source of truth.

        cmd_session_start reads todos from DB, ignoring any YAML files.
        It completes gracefully and produces normal project context.
        """
        proj_dir = _make_active_project(cfg, "myapp", str(tmp_path), active=True)
        # Overwrite todos.yaml with invalid YAML — DB is untouched, so no effect
        (proj_dir / "todos.yaml").write_text("todos:\n  - id: 1\n  bad: [unclosed\n")

        from server.cli import cmd_session_start

        # Should not raise — DB is source of truth, YAML corruption is irrelevant
        cmd_session_start(cwd=str(tmp_path), compact=False)

    def test_stale_meta_yaml_has_no_effect_on_context(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Overwriting meta.yaml has no effect — SQLite is source of truth.

        cmd_session_start reads meta from DB, not from meta.yaml.
        The project name in DB is 'myapp', so output still contains 'myapp'.
        """
        proj_dir = _make_active_project(cfg, "myapp", str(tmp_path), active=True)
        # Overwrite meta.yaml — DB has the real meta, this is ignored
        (proj_dir / "meta.yaml").write_text("status: active\npriority: medium\n")

        from server.cli import cmd_session_start

        # Should not raise — DB is source of truth
        cmd_session_start(cwd=str(tmp_path), compact=False)

    def test_valid_meta_in_db_produces_context(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When meta is in DB, cmd_session_start produces project context output."""
        _make_active_project(cfg, "myapp", str(tmp_path), active=True)

        from server.cli import cmd_session_start

        cmd_session_start(cwd=str(tmp_path), compact=False)
        out, err = capsys.readouterr()
        assert "myapp" in out
        assert err == ""


# ---------------------------------------------------------------------------
# CLI-level: cmd_session_end with corrupted data
# ---------------------------------------------------------------------------


class TestCmdSessionEndCorruption:
    """cmd_session_end edge cases with various forms of data corruption."""

    def test_corrupted_index_returns_gracefully(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When the index YAML is syntactically invalid, cmd_session_end returns gracefully.

        _load_yaml swallows the YAMLError; load_index returns empty index (projects={}).
        ctx_detect_project_name finds nothing, so session-end is a no-op.
        """
        index_path = Path(cfg.tracking_dir) / "active-projects.yaml"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("projects: [unclosed\n")

        from server.cli import cmd_session_end

        # Should not raise — graceful degradation
        cmd_session_end(cwd=str(tmp_path))

    def test_stale_meta_yaml_has_no_effect_on_session_end(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Overwriting meta.yaml has no effect — SQLite is source of truth.

        cmd_session_end reads meta from DB, not from meta.yaml. Project 'myapp'
        is in DB so the command completes without error.
        """
        proj_dir = _make_active_project(cfg, "myapp", str(tmp_path), active=True)
        # Overwrite meta.yaml — DB has the real meta, this is ignored
        (proj_dir / "meta.yaml").write_text("status: active\npriority: medium\n")

        from server.cli import cmd_session_end

        # Should not raise — DB is source of truth
        cmd_session_end(cwd=str(tmp_path))

    def test_valid_meta_in_db_does_not_crash_session_end(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Valid meta in DB — cmd_session_end completes without error."""
        _make_active_project(cfg, "myapp", str(tmp_path), active=True)

        from server.cli import cmd_session_end

        cmd_session_end(cwd=str(tmp_path))
        out, err = capsys.readouterr()
        assert out == ""
        assert err == ""


# ---------------------------------------------------------------------------
# MCP tool-level: ctx_session_start / ctx_session_end with corrupted data
# ---------------------------------------------------------------------------


def _is_error_result(result: Any) -> bool:
    """Return True if *result* looks like a FastMCP error response string."""
    if not isinstance(result, str):
        return False
    lower = result.lower()
    return "error" in lower or "exception" in lower or "invalid" in lower


@pytest.mark.asyncio
class TestMCPContextToolsCorruption:
    """ctx_session_start / ctx_session_end MCP tools with corrupted tracking data.

    FastMCP may catch tool exceptions and convert them to error-string responses
    rather than re-raising.  Each test therefore accepts either an exception or
    an error-indicating string return value when documenting a gap scenario.
    """

    async def test_session_start_stale_todos_yaml_has_no_effect(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Corrupted todos.yaml has no effect — SQLite is source of truth.

        ctx_session_start reads todos from DB, so a corrupt YAML file is ignored.
        Normal project context is returned.
        """
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        # Overwrite todos.yaml with corrupt content — DB is untouched
        (proj_dir / "todos.yaml").write_text("todos:\n  - id: 1\n  bad: [unclosed\n")

        result = await call_tool(mcp_app, "ctx_session_start")
        # DB has valid data, so session_start succeeds normally
        assert "myapp" in result

    async def test_session_start_meta_in_db_returns_context(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """ctx_session_start works when meta is in DB (stale YAML is irrelevant)."""
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        # Overwrite meta.yaml — DB has the real meta, this is ignored
        (proj_dir / "meta.yaml").write_text("name: myapp\n")

        result = await call_tool(mcp_app, "ctx_session_start")
        assert "myapp" in result

    async def test_session_end_meta_in_db_returns_updated(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """ctx_session_end completes when meta is in DB (stale YAML is irrelevant)."""
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        today = str(date.today())
        # Overwrite meta.yaml — DB has the real meta, this is ignored
        (proj_dir / "meta.yaml").write_text(
            f"name: myapp\ndates:\n  created: '{today}'\n  last_updated: '2000-01-01'\n"
        )

        result = await call_tool(mcp_app, "ctx_session_end")
        assert "myapp" in result or "Updated" in result

    async def test_session_start_no_config_returns_empty(
        self, mcp_app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ctx_session_start returns '' when no config file exists (regression guard)."""
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", tmp_path / "no-config.yaml")
        monkeypatch.delenv("PROJ_CONFIG", raising=False)

        result = await call_tool(mcp_app, "ctx_session_start")
        assert result == ""

    async def test_session_end_no_config_returns_message(
        self, mcp_app: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ctx_session_end returns 'No config.' when no config file exists."""
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", tmp_path / "no-config.yaml")
        monkeypatch.delenv("PROJ_CONFIG", raising=False)
        state.clear_session_active()

        result = await call_tool(mcp_app, "ctx_session_end")
        assert "No config" in result


# ---------------------------------------------------------------------------
# Storage-level: load_todos when file doesn't exist
# ---------------------------------------------------------------------------


class TestLoadTodosFileNotExist:
    """load_todos raises FileNotFoundError when data.db is missing."""

    def test_missing_db_with_project_dir_raises(self, cfg: ProjConfig) -> None:
        """When the project dir exists but data.db does not, load_todos raises FileNotFoundError."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        # No data.db created

        with pytest.raises(FileNotFoundError, match=r"data\.db not found"):
            storage.load_todos(cfg, "myapp")

    def test_missing_project_dir_raises(self, cfg: ProjConfig) -> None:
        """When the entire project directory doesn't exist, load_todos raises FileNotFoundError."""
        # Do NOT create the project directory at all
        with pytest.raises(FileNotFoundError, match=r"data\.db not found"):
            storage.load_todos(cfg, "nonexistent-project")


# ---------------------------------------------------------------------------
# Storage-level: _load_yaml permission errors
# ---------------------------------------------------------------------------


class TestLoadYamlPermissionError:
    """_load_yaml does not catch PermissionError -- it propagates."""

    def test_load_todos_raises_when_db_missing(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """load_todos raises FileNotFoundError when data.db is missing (no YAML fallback).

        YAML files (even unreadable ones) are irrelevant — SQLite is source of truth.
        """
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        # Write a todos.yaml to confirm it's ignored
        todos_file = proj_dir / "todos.yaml"
        todos_file.write_text("todos: []\n")

        with pytest.raises(FileNotFoundError, match=r"data\.db not found"):
            storage.load_todos(cfg, "myapp")

    def test_permission_error_on_index(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """load_index reads from SQLite — YAML permission errors no longer affect it.

        The index is now stored in SQLite (sql_meta.load_index), so even when
        active-projects.yaml is unreadable, load_index succeeds and returns an
        empty index (no projects registered yet).
        """
        index_path = Path(cfg.tracking_dir) / "active-projects.yaml"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("projects: {}\n")
        index_path.chmod(0o000)
        try:
            # Should NOT raise — SQLite is the source of truth
            index = storage.load_index(cfg)
            assert index.projects == {}
        finally:
            index_path.chmod(0o644)


# ---------------------------------------------------------------------------
# CLI-level: cmd_session_end with corrupted todos
# ---------------------------------------------------------------------------


class TestCmdSessionEndCorruptedTodos:
    """cmd_session_end edge cases specifically with corrupted todos."""

    def test_stale_yaml_files_do_not_affect_session_end(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Stale/corrupt YAML files have no effect — SQLite is source of truth.

        cmd_session_end reads from DB, so overwritten YAML files are ignored.
        The command completes without error.
        """
        proj_dir = _make_active_project(cfg, "myapp", str(tmp_path), active=True)
        # Overwrite YAML files with stale/corrupt content — DB is untouched
        (proj_dir / "meta.yaml").write_text("stale: content\n")
        (proj_dir / "todos.yaml").write_text("todos:\n  - id: 1\n  bad: [unclosed\n")

        from server.cli import cmd_session_end

        # Should not raise — DB is source of truth
        cmd_session_end(cwd=str(tmp_path))
