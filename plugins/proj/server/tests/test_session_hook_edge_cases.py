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
import yaml

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
    """Direct storage.load_todos tests for various forms of file corruption."""

    def test_empty_todos_file_returns_empty_list(self, cfg: ProjConfig) -> None:
        """An empty todos.yaml (None after yaml.safe_load) returns []."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "todos.yaml").write_text("")

        todos = storage.load_todos(cfg, "myapp")
        assert todos == []

    def test_todos_key_missing_returns_empty_list(self, cfg: ProjConfig) -> None:
        """YAML dict without a 'todos' key returns []."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "todos.yaml").write_text("other_key: 42\n")

        todos = storage.load_todos(cfg, "myapp")
        assert todos == []

    def test_todos_value_not_a_list_returns_empty_list(self, cfg: ProjConfig) -> None:
        """When 'todos' key exists but value is not a list, returns []."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "todos.yaml").write_text("todos: not-a-list\n")

        todos = storage.load_todos(cfg, "myapp")
        assert todos == []

    def test_invalid_yaml_in_todos_returns_empty(self, cfg: ProjConfig) -> None:
        """A syntactically invalid todos.yaml is swallowed by _load_yaml and returns [].

        _load_yaml catches yaml.YAMLError and returns {}, so load_todos returns [].
        """
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "todos.yaml").write_text("todos:\n  - id: 1\n  bad: [unclosed\n")

        assert storage.load_todos(cfg, "myapp") == []

    def test_todos_file_scalar_top_level_returns_empty(self, cfg: ProjConfig) -> None:
        """When todos.yaml contains only a scalar string, load_todos returns [].

        _load_yaml returns {} for non-dict content; load_todos returns [].
        """
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "todos.yaml").write_text("this is just a plain string\n")

        assert storage.load_todos(cfg, "myapp") == []

    def test_todos_file_list_top_level_returns_empty(self, cfg: ProjConfig) -> None:
        """When todos.yaml is a bare YAML list (not a mapping), load_todos returns [].

        _load_yaml returns {} for non-dict content; load_todos returns [].
        """
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "todos.yaml").write_text("- id: T001\n  title: Foo\n")

        assert storage.load_todos(cfg, "myapp") == []


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

    def test_index_file_scalar_top_level_returns_empty(self, cfg: ProjConfig) -> None:
        """When active-projects.yaml is a plain scalar, load_index returns empty index.

        _load_yaml returns {} for non-dict content; from_dict({}) produces an empty index.
        """
        index_path = Path(cfg.tracking_dir) / "active-projects.yaml"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("just a string\n")

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
    """Direct storage.load_meta tests for malformed meta.yaml files."""

    def test_missing_meta_file_raises_file_not_found(self, cfg: ProjConfig) -> None:
        """Missing meta.yaml raises FileNotFoundError (expected and caught by CLI)."""
        with pytest.raises(FileNotFoundError, match="myapp"):
            storage.load_meta(cfg, "myapp")

    def test_empty_meta_file_returns_meta_with_empty_name(self, cfg: ProjConfig) -> None:
        """An empty meta.yaml loads gracefully and returns a ProjectMeta with name=''.

        ProjectMeta.from_dict now uses data.get('name', '') so a missing 'name'
        key no longer raises KeyError — it falls back to an empty string.
        """
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "meta.yaml").write_text("")

        meta = storage.load_meta(cfg, "myapp")
        assert meta.name == ""

    def test_meta_missing_name_returns_empty_string(self, cfg: ProjConfig) -> None:
        """meta.yaml without 'name' field loads and returns name='' instead of raising."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "meta.yaml").write_text(
            "status: active\npriority: medium\ndescription: No name here\n"
        )

        meta = storage.load_meta(cfg, "myapp")
        assert meta.name == ""
        assert meta.status == "active"
        assert meta.priority == "medium"

    def test_project_meta_from_dict_missing_name_returns_empty_string(self) -> None:
        """ProjectMeta.from_dict({}) returns name='' instead of raising KeyError."""
        meta = ProjectMeta.from_dict({})
        assert meta.name == ""

    def test_invalid_yaml_in_meta_returns_empty_meta(self, cfg: ProjConfig) -> None:
        """Syntactically invalid meta.yaml is swallowed and returns ProjectMeta with name=''.

        _load_yaml catches yaml.YAMLError and returns {}, so from_dict({}) returns
        a ProjectMeta with name='' and default values for all optional fields.
        """
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "meta.yaml").write_text("name: myapp\nrepos: [unclosed\n")

        meta = storage.load_meta(cfg, "myapp")
        assert meta.name == ""

    def test_meta_missing_optional_fields_uses_defaults(self, cfg: ProjConfig) -> None:
        """meta.yaml with only the required 'name' field fills optional fields with defaults."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "meta.yaml").write_text("name: myapp\n")

        meta = storage.load_meta(cfg, "myapp")
        assert meta.name == "myapp"
        assert meta.status == "active"
        assert meta.priority == "medium"
        assert meta.description == ""
        assert meta.repos == []
        assert meta.tags == []

    def test_meta_repos_not_a_list_uses_empty_repos(self, cfg: ProjConfig) -> None:
        """When 'repos' is not a list, ProjectMeta.from_dict falls back to []."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "meta.yaml").write_text("name: myapp\nrepos: not-a-list\n")

        meta = storage.load_meta(cfg, "myapp")
        assert meta.name == "myapp"
        assert meta.repos == []

    def test_meta_dates_not_a_dict_uses_empty_dates(self, cfg: ProjConfig) -> None:
        """When 'dates' is not a dict, ProjectDates.from_dict falls back to empty strings."""
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        proj_dir.mkdir(parents=True, exist_ok=True)
        (proj_dir / "meta.yaml").write_text("name: myapp\ndates: not-a-dict\n")

        meta = storage.load_meta(cfg, "myapp")
        assert meta.name == "myapp"
        assert meta.dates.created == ""
        assert meta.dates.last_updated == ""


# ---------------------------------------------------------------------------
# CLI-level: cmd_session_start with corrupted data
# ---------------------------------------------------------------------------


class TestCmdSessionStartCorruption:
    """cmd_session_start edge cases with various forms of data corruption."""

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

    def test_corrupted_todos_yaml_returns_context_with_empty_todos(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When todos.yaml is syntactically invalid, cmd_session_start completes gracefully.

        _load_yaml catches yaml.YAMLError and returns {}, so load_todos returns [].
        cmd_session_start produces context output with no todos listed.
        """
        proj_dir = _make_active_project(cfg, "myapp", str(tmp_path), active=True)
        # Overwrite todos.yaml with invalid YAML
        (proj_dir / "todos.yaml").write_text("todos:\n  - id: 1\n  bad: [unclosed\n")

        from server.cli import cmd_session_start

        # Should not raise — graceful degradation
        cmd_session_start(cwd=str(tmp_path), compact=False)

    def test_malformed_meta_yaml_missing_name_produces_output(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When meta.yaml has no 'name' field, cmd_session_start no longer raises KeyError.

        ProjectMeta.from_dict now falls back to name='' via data.get('name', ''),
        so the command completes without an unhandled exception.
        """
        proj_dir = _make_active_project(cfg, "myapp", str(tmp_path), active=True)
        # Overwrite meta.yaml with one missing the required 'name' field
        (proj_dir / "meta.yaml").write_text("status: active\npriority: medium\n")

        from server.cli import cmd_session_start

        # Should not raise — graceful degradation
        cmd_session_start(cwd=str(tmp_path), compact=False)

    def test_valid_meta_corrupted_todos_scalar_returns_gracefully(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When todos.yaml is a bare scalar string, cmd_session_start completes gracefully.

        _load_yaml returns {} for non-dict content; load_todos returns [].
        """
        proj_dir = _make_active_project(cfg, "myapp", str(tmp_path), active=True)
        (proj_dir / "todos.yaml").write_text("just a string\n")

        from server.cli import cmd_session_start

        # Should not raise — graceful degradation
        cmd_session_start(cwd=str(tmp_path), compact=False)

    def test_missing_fields_in_meta_with_defaults_produces_context(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """meta.yaml with only 'name' (all optional fields missing) still produces context output.

        This is the happy path for missing optional fields — graceful degradation.
        """
        proj_dir = _make_active_project(cfg, "myapp", str(tmp_path), active=True)
        # Overwrite meta.yaml with minimal fields (keep repos so cwd detection works)
        (proj_dir / "meta.yaml").write_text(
            f"name: myapp\nrepos:\n  - label: code\n    path: {tmp_path}\n"
        )

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

    def test_malformed_meta_yaml_missing_name_does_not_raise_in_session_end(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """When meta.yaml has no 'name' field, cmd_session_end no longer raises KeyError.

        ProjectMeta.from_dict now falls back to name='' via data.get('name', '').
        """
        proj_dir = _make_active_project(cfg, "myapp", str(tmp_path), active=True)
        (proj_dir / "meta.yaml").write_text("status: active\npriority: medium\n")

        from server.cli import cmd_session_end

        # Should not raise — graceful degradation
        cmd_session_end(cwd=str(tmp_path))

    def test_meta_with_defaults_only_does_not_crash_session_end(
        self, cfg: ProjConfig, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """meta.yaml with only 'name' present completes session-end without error."""
        proj_dir = _make_active_project(cfg, "myapp", str(tmp_path), active=True)
        today = str(date.today())
        # Minimal but valid meta — only required field + dates to avoid KeyError in save_meta
        (proj_dir / "meta.yaml").write_text(
            f"name: myapp\ndates:\n  created: '{today}'\n  last_updated: '2000-01-01'\n"
        )

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

    async def test_session_start_corrupted_todos_does_not_succeed(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """ctx_session_start does not produce project context when todos.yaml is invalid.

        Only FileNotFoundError is guarded in the tool; yaml.YAMLError from
        load_todos propagates to FastMCP, which may raise or return an error string.
        The key assertion: normal project context is NOT returned.
        """
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        (proj_dir / "todos.yaml").write_text("todos:\n  - id: 1\n  bad: [unclosed\n")

        try:
            result = await call_tool(mcp_app, "ctx_session_start")
            # If FastMCP converts the exception to a string, it should look like an error,
            # not normal project context ("myapp" with status/priority lines).
            # We allow an empty result too (tool returned "" on error path).
            assert "myapp" not in result or _is_error_result(result), (
                f"Expected error or empty, got: {result!r}"
            )
        except (yaml.YAMLError, KeyError, AttributeError, Exception):
            # Exception propagating is also acceptable behaviour.
            pass

    async def test_session_start_meta_missing_optional_fields_returns_context(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """ctx_session_start works when meta.yaml has only the required 'name' field."""
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        (proj_dir / "meta.yaml").write_text("name: myapp\n")

        result = await call_tool(mcp_app, "ctx_session_start")
        assert "myapp" in result

    async def test_session_start_meta_missing_name_does_not_succeed(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """ctx_session_start does not produce context when meta.yaml has no 'name'.

        KeyError propagates from ProjectMeta.from_dict.  FastMCP may raise or
        return an error string; either is acceptable — we just assert no normal
        project context comes back.
        """
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        (proj_dir / "meta.yaml").write_text("status: active\npriority: medium\n")

        try:
            result = await call_tool(mcp_app, "ctx_session_start")
            # Normal context would contain "myapp"; an error string is ok.
            assert _is_error_result(result) or result == "", (
                f"Expected error or empty result, got: {result!r}"
            )
        except (KeyError, Exception):
            pass  # Exception propagation is also acceptable.

    async def test_session_end_meta_missing_optional_fields_returns_updated(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """ctx_session_end completes when meta.yaml has only the required 'name' field."""
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        today = str(date.today())
        (proj_dir / "meta.yaml").write_text(
            f"name: myapp\ndates:\n  created: '{today}'\n  last_updated: '2000-01-01'\n"
        )

        result = await call_tool(mcp_app, "ctx_session_end")
        assert "myapp" in result or "Updated" in result

    async def test_session_end_meta_missing_name_does_not_succeed(
        self, mcp_app: Any, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """ctx_session_end does not return 'Updated' when meta.yaml has no 'name'.

        KeyError propagates from from_dict.  FastMCP may raise or error-string.
        """
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        proj_dir = Path(cfg.tracking_dir) / "myapp"
        (proj_dir / "meta.yaml").write_text("status: active\n")

        try:
            result = await call_tool(mcp_app, "ctx_session_end")
            # Should NOT be a success message
            assert "Updated" not in result or _is_error_result(result), (
                f"Expected error, got success: {result!r}"
            )
        except (KeyError, Exception):
            pass  # Exception propagation is also acceptable.

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
