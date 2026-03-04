"""Integration tests for proj MCP tools — calls tools via FastMCP directly."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    RepoEntry,
)


@pytest.fixture()
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    c = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(c)
    return c


def _setup_project(cfg: ProjConfig, name: str, tmp_path: Path) -> None:
    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / name
    proj_dir.mkdir(parents=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "NOTES.md").write_text(f"# {name}\n")
    meta = ProjectMeta(
        name=name,
        repos=[RepoEntry(label="code", path=str(tmp_path))],
        dates=ProjectDates(created=today, last_updated=today),
    )
    storage.save_meta(cfg, meta)
    index = ProjectIndex(
        active=name,
        projects={name: ProjectEntry(name=name, tracking_dir=str(proj_dir), created=today)},
    )
    storage.save_index(cfg, index)


class TestConfigTools:
    def test_config_load_returns_info(self, cfg: ProjConfig) -> None:
        from server.tools.config import require_config

        loaded = require_config()
        assert loaded.tracking_dir == cfg.tracking_dir

    def test_config_not_found_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from server.tools.config import ConfigError, require_config

        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", tmp_path / "missing.yaml")
        monkeypatch.delenv("PROJ_CONFIG", raising=False)
        with pytest.raises(ConfigError):
            require_config()


class TestProjectsTools:
    def test_proj_init_via_storage(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _setup_project(cfg, "myapp", tmp_path)
        index = storage.load_index(cfg)
        assert "myapp" in index.projects
        assert index.active == "myapp"

    def test_proj_archive(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _setup_project(cfg, "myapp", tmp_path)
        index = storage.load_index(cfg)
        index.projects["myapp"].archived = True
        if index.active == "myapp":
            index.active = None
        storage.save_index(cfg, index)
        index = storage.load_index(cfg)
        assert index.projects["myapp"].archived
        assert index.active is None


class TestTodosTools:
    def test_add_todo_increments_id(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _setup_project(cfg, "myapp", tmp_path)
        from server.lib.ids import next_todo_id
        from server.lib.models import Todo

        meta = storage.load_meta(cfg, "myapp")
        t1 = Todo(id=next_todo_id(meta), title="T1", created="2026-01-01", updated="2026-01-01")
        t2 = Todo(id=next_todo_id(meta), title="T2", created="2026-01-01", updated="2026-01-01")
        storage.save_todos(cfg, "myapp", [t1, t2])
        storage.save_meta(cfg, meta)
        todos = storage.load_todos(cfg, "myapp")
        assert todos[0].id == "1"
        assert todos[1].id == "2"

    def test_blocked_todo(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _setup_project(cfg, "myapp", tmp_path)
        from server.lib.ids import next_todo_id
        from server.lib.models import Todo

        meta = storage.load_meta(cfg, "myapp")
        t1 = Todo(
            id=next_todo_id(meta), title="Blocker", created="2026-01-01", updated="2026-01-01"
        )
        t2 = Todo(
            id=next_todo_id(meta),
            title="Blocked",
            blocked_by=[t1.id],
            created="2026-01-01",
            updated="2026-01-01",
        )
        t1.blocks.append(t2.id)
        storage.save_todos(cfg, "myapp", [t1, t2])
        todos = storage.load_todos(cfg, "myapp")
        ready = [t for t in todos if t.status == "pending" and not t.blocked_by]
        assert len(ready) == 1
        assert ready[0].id == t1.id


class TestContextTools:
    def test_detect_project_by_cwd(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _setup_project(cfg, "myapp", tmp_path)
        from server.tools.context import ctx_detect_project_name

        result = ctx_detect_project_name(str(tmp_path))
        assert result == "myapp"

    def test_detect_no_match(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _setup_project(cfg, "myapp", tmp_path)
        from server.tools.context import ctx_detect_project_name

        result = ctx_detect_project_name("/nonexistent/path")
        assert result is None

    def test_session_start_output(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _setup_project(cfg, "myapp", tmp_path)
        from server.tools.context import _build_context

        output = _build_context(cfg, "myapp")
        assert "myapp" in output

    def test_append_note(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _setup_project(cfg, "myapp", tmp_path)
        storage.append_note(cfg, "myapp", "Important note here")
        notes = storage.read_notes(cfg, "myapp")
        assert "Important note here" in notes

    def test_read_recent_notes_returns_last_three_sections(
        self, cfg: ProjConfig, tmp_path: Path
    ) -> None:
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

    def test_read_recent_notes_no_dated_headers_fallback(
        self, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        from server.tools.context import _read_recent_notes

        notes_file = tmp_path / "NOTES.md"
        notes_file.write_text("# Project Notes\n\nSome plain content without dated sections.\n")
        result = _read_recent_notes(notes_file, max_chars=600)
        assert "plain content" in result

    def test_read_recent_notes_empty_file(self, cfg: ProjConfig, tmp_path: Path) -> None:
        from server.tools.context import _read_recent_notes

        notes_file = tmp_path / "NOTES.md"
        notes_file.write_text("")
        result = _read_recent_notes(notes_file)
        assert result == ""

    def test_read_recent_notes_nonexistent_file(
        self, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        from server.tools.context import _read_recent_notes

        notes_file = tmp_path / "DOES_NOT_EXIST.md"
        result = _read_recent_notes(notes_file)
        assert result == ""

    def test_build_context_compact_skips_notes(
        self, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        _setup_project(cfg, "myapp", tmp_path)
        storage.append_note(cfg, "myapp", "A note that should be hidden")
        from server.tools.context import _build_context

        output = _build_context(cfg, "myapp", compact=True)
        assert "A note that should be hidden" not in output
        assert "Recent Notes" not in output


class TestContentTools:
    def test_requirements_via_storage(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _setup_project(cfg, "myapp", tmp_path)
        storage.write_requirements(cfg, "myapp", "T001", "# Requirements\nGoal: X")
        content = storage.read_requirements(cfg, "myapp", "T001")
        assert content is not None
        assert "Goal: X" in content

    def test_research_via_storage(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _setup_project(cfg, "myapp", tmp_path)
        storage.write_research(cfg, "myapp", "T001", "# Research\nApproach: Y")
        content = storage.read_research(cfg, "myapp", "T001")
        assert content is not None
        assert "Approach: Y" in content
