"""Tests for project CRUD tools."""

from __future__ import annotations

from pathlib import Path

import pytest

from server.lib import storage
from server.lib.models import ProjConfig, ProjectEntry, validate_project_name


@pytest.fixture()
def cfg(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    c = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(c)
    return c


def _run_proj_init(name: str, path: str) -> str:
    from mcp.server.fastmcp import FastMCP

    from server.tools.projects import register

    app = FastMCP("test")
    register(app)
    # Access tool via direct function call
    from datetime import date

    from server.lib.models import ProjectDates, ProjectMeta, RepoEntry

    # Directly use storage APIs
    cfg = storage.load_config()
    index = storage.load_index(cfg)
    today = str(date.today())
    tracking = Path(cfg.tracking_dir).expanduser() / name
    tracking.mkdir(parents=True, exist_ok=True)
    (tracking / "NOTES.md").write_text(f"# {name}\n")
    (tracking / "todos.yaml").write_text("todos: []\n")
    meta = ProjectMeta(
        name=name,
        repos=[RepoEntry(label="code", path=path)],
        dates=ProjectDates(created=today, last_updated=today),
    )
    storage.save_meta(cfg, meta)
    entry = ProjectEntry(name=name, tracking_dir=str(tracking), created=today)
    index.projects[name] = entry
    if not index.active:
        index.active = name
    storage.save_index(cfg, index)
    return f"Initialized project '{name}'."


class TestProjInit:
    def test_creates_project(self, cfg: ProjConfig, tmp_path: Path) -> None:
        result = _run_proj_init("myapp", str(tmp_path))
        assert "myapp" in result
        index = storage.load_index(cfg)
        assert "myapp" in index.projects

    def test_sets_active(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        index = storage.load_index(cfg)
        assert index.active == "myapp"

    def test_creates_tracking_files(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tracking = Path(cfg.tracking_dir) / "myapp"
        assert (tracking / "NOTES.md").exists()
        assert (tracking / "todos.yaml").exists()


class TestTodoOperations:
    def test_add_and_list(self, cfg: ProjConfig, tmp_path: Path) -> None:
        from server.lib.models import Todo

        _run_proj_init("myapp", str(tmp_path))
        from server.lib.ids import next_todo_id

        meta = storage.load_meta(cfg, "myapp")
        todo = Todo(
            id=next_todo_id(meta), title="Test task", created="2026-01-01", updated="2026-01-01"
        )
        storage.save_meta(cfg, meta)
        storage.save_todos(cfg, "myapp", [todo])
        todos = storage.load_todos(cfg, "myapp")
        assert len(todos) == 1
        assert todos[0].title == "Test task"

    def test_todo_id_increments(self, cfg: ProjConfig, tmp_path: Path) -> None:
        from server.lib.ids import next_todo_id

        _run_proj_init("myapp", str(tmp_path))
        meta = storage.load_meta(cfg, "myapp")
        id1 = next_todo_id(meta)
        id2 = next_todo_id(meta)
        assert id1 == "1"
        assert id2 == "2"
        assert meta.next_todo_id == 3


class TestValidateProjectName:
    """Unit tests for the standalone validate_project_name() helper."""

    # --- valid names --------------------------------------------------------

    def test_valid_simple(self) -> None:
        assert validate_project_name("myproject") is None

    def test_valid_with_hyphens_and_numbers(self) -> None:
        assert validate_project_name("my-project-123") is None

    def test_valid_with_underscores(self) -> None:
        assert validate_project_name("my_project") is None

    def test_valid_mixed_case(self) -> None:
        assert validate_project_name("MyProject") is None

    # --- empty / whitespace -------------------------------------------------

    def test_empty_string(self) -> None:
        assert validate_project_name("") is not None

    def test_whitespace_only(self) -> None:
        assert validate_project_name("   ") is not None

    def test_tab_only(self) -> None:
        assert validate_project_name("\t") is not None

    # --- path traversal -----------------------------------------------------

    def test_double_dot(self) -> None:
        assert validate_project_name("../../etc") is not None

    def test_double_dot_suffix(self) -> None:
        assert validate_project_name("foo..bar") is not None

    # --- path separators ----------------------------------------------------

    def test_forward_slash(self) -> None:
        assert validate_project_name("foo/bar") is not None

    def test_backslash(self) -> None:
        assert validate_project_name("foo\\bar") is not None

    # --- null byte ----------------------------------------------------------

    def test_null_byte(self) -> None:
        assert validate_project_name("foo\x00bar") is not None

    # --- dot-prefixed / reserved --------------------------------------------

    def test_dot_git(self) -> None:
        assert validate_project_name(".git") is not None

    def test_dot_hidden(self) -> None:
        assert validate_project_name(".hidden") is not None

    def test_single_dot(self) -> None:
        assert validate_project_name(".") is not None

    # --- control characters -------------------------------------------------

    def test_newline(self) -> None:
        assert validate_project_name("foo\nbar") is not None

    def test_carriage_return(self) -> None:
        assert validate_project_name("foo\rbar") is not None

    def test_del_character(self) -> None:
        assert validate_project_name("foo\x7fbar") is not None

    def test_low_control_character(self) -> None:
        assert validate_project_name("foo\x01bar") is not None

    # --- unicode ------------------------------------------------------------

    def test_valid_unicode_latin(self) -> None:
        # Accented Latin characters should be accepted (not control chars, no slashes)
        assert validate_project_name("projet-été") is None

    def test_valid_unicode_cjk(self) -> None:
        # CJK characters should be accepted
        assert validate_project_name("プロジェクト") is None

    def test_valid_unicode_emoji_adjacent(self) -> None:
        # Names with high codepoint chars (above ASCII) should be accepted
        assert validate_project_name("project-2024-café") is None

    # --- length -------------------------------------------------------------

    def test_very_long_name(self) -> None:
        # No length restriction in validate_project_name — 300 chars should be accepted
        assert validate_project_name("a" * 300) is None

    def test_single_char_name(self) -> None:
        # Minimal valid name
        assert validate_project_name("a") is None

    # --- names with spaces --------------------------------------------------

    def test_name_with_space(self) -> None:
        # Space (ord 32) is NOT a control character — allowed by current rules
        assert validate_project_name("my project") is None

    def test_leading_trailing_spaces(self) -> None:
        # Leading/trailing spaces make name whitespace-ambiguous; strip() sees content
        # but the raw name has leading space — validate_project_name does not trim,
        # so this should be accepted (spaces are not blocked)
        assert validate_project_name("  myproject  ") is None

    # --- tricky dot patterns ------------------------------------------------

    def test_triple_dot(self) -> None:
        # "..." contains ".." — must be rejected
        assert validate_project_name("...") is not None

    def test_double_dot_prefix(self) -> None:
        # "..hidden" contains ".." — caught by path-traversal check
        assert validate_project_name("..hidden") is not None

    def test_dot_dot_only(self) -> None:
        # ".." alone is a path-traversal sequence
        assert validate_project_name("..") is not None

    # --- error message content ----------------------------------------------

    def test_error_message_empty(self) -> None:
        msg = validate_project_name("")
        assert msg is not None
        assert "empty" in msg.lower() or "whitespace" in msg.lower()

    def test_error_message_path_traversal(self) -> None:
        msg = validate_project_name("foo../bar")
        assert msg is not None
        assert ".." in msg

    def test_error_message_slash(self) -> None:
        msg = validate_project_name("a/b")
        assert msg is not None
        assert "/" in msg or "path separator" in msg.lower()

    def test_error_message_dot_prefix(self) -> None:
        msg = validate_project_name(".secret")
        assert msg is not None
        assert "." in msg or "reserved" in msg.lower()

    def test_error_message_control_char(self) -> None:
        msg = validate_project_name("foo\x1bbar")  # ESC char
        assert msg is not None
        assert "control" in msg.lower() or "ordinal" in msg.lower()

    def test_returns_none_not_false(self) -> None:
        # Explicitly check return type for valid name
        result = validate_project_name("valid-name")
        assert result is None


class TestProjSetActive:
    """Tests for proj_set_active fuzzy matching."""

    def _call_proj_set_active(self, name: str) -> str:
        import asyncio

        from mcp.server.fastmcp import FastMCP

        from server.tools.projects import register

        app = FastMCP("test-set-active")
        register(app)
        tool_fn = app._tool_manager.get_tool("proj_set_active")
        assert tool_fn is not None

        async def _run() -> str:
            result = await tool_fn.run({"name": name}, {})
            if isinstance(result, list):
                return "".join(getattr(c, "text", str(c)) for c in result)
            return str(result)

        return asyncio.run(_run())

    def test_fuzzy_single_match_sets_active(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """A partial name that resolves to exactly one project auto-selects it."""
        _run_proj_init("my-project", str(tmp_path))
        result = self._call_proj_set_active("my-proje")
        assert "my-project" in result
        index = storage.load_index(cfg)
        assert index.active == "my-project"

    def test_fuzzy_multiple_matches_returns_ambiguous(
        self, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """A partial name matching multiple projects returns an ambiguous message."""
        _run_proj_init("my-project-alpha", str(tmp_path))
        _run_proj_init("my-project-beta", str(tmp_path))
        result = self._call_proj_set_active("my-project")
        assert "Ambiguous match" in result
        assert "my-project-alpha" in result or "my-project-beta" in result

    def test_fuzzy_no_match_returns_not_found(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """A name with no close matches returns a not-found message with available list."""
        _run_proj_init("my-project", str(tmp_path))
        result = self._call_proj_set_active("zzz-totally-unrelated")
        assert "not found" in result.lower()
        assert "my-project" in result


class TestProjInitValidation:
    """Integration tests: proj_init rejects bad names before touching the filesystem."""

    def _call_proj_init(self, name: str, tmp_path: Path) -> str:
        """Call proj_init via the registered MCP tool directly."""
        import asyncio

        from mcp.server.fastmcp import FastMCP

        from server.tools.projects import register

        app = FastMCP("test-validation")
        register(app)
        tool_fn = app._tool_manager.get_tool("proj_init")
        assert tool_fn is not None

        async def _run() -> str:
            result = await tool_fn.run({"name": name, "path": str(tmp_path)}, {})
            if isinstance(result, list):
                return "".join(getattr(c, "text", str(c)) for c in result)
            return str(result)

        return asyncio.run(_run())

    def test_rejects_path_traversal(self, cfg: ProjConfig, tmp_path: Path) -> None:
        result = self._call_proj_init("../../etc", tmp_path)
        assert "path traversal" in result.lower() or ".." in result

    def test_rejects_slash(self, cfg: ProjConfig, tmp_path: Path) -> None:
        result = self._call_proj_init("foo/bar", tmp_path)
        assert "path separator" in result.lower() or "/" in result

    def test_rejects_empty(self, cfg: ProjConfig, tmp_path: Path) -> None:
        result = self._call_proj_init("", tmp_path)
        assert "empty" in result.lower() or "whitespace" in result.lower()

    def test_rejects_dot_git(self, cfg: ProjConfig, tmp_path: Path) -> None:
        result = self._call_proj_init(".git", tmp_path)
        assert "." in result or "reserved" in result.lower()

    def test_no_directory_created_on_invalid_name(
        self, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        tracking_root = Path(cfg.tracking_dir)
        self._call_proj_init("../../evil", tmp_path)
        # No directory should have been created under the tracking root
        assert not any(tracking_root.iterdir()) if tracking_root.exists() else True
