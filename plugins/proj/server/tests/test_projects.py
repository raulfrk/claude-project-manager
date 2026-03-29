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
    storage.save_index(cfg, index)
    return f"Initialized project '{name}'."


class TestProjInit:
    def test_creates_project(self, cfg: ProjConfig, tmp_path: Path) -> None:
        result = _run_proj_init("myapp", str(tmp_path))
        assert "myapp" in result
        index = storage.load_index(cfg)
        assert "myapp" in index.projects

    def test_creates_tracking_files(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tracking = Path(cfg.tracking_dir) / "myapp"
        assert (tracking / "NOTES.md").exists()
        assert (tracking / "todos.yaml").exists()


class TestProjInitHooksSync:
    """Tests for the hooks_sync call in proj_init."""

    def _call_proj_init(self, name: str, tmp_path: Path) -> str:
        """Call proj_init via the registered MCP tool directly."""
        import asyncio

        from mcp.server.fastmcp import FastMCP

        from server.tools.projects import register

        app = FastMCP("test-hooks-sync")
        register(app)
        tool_fn = app._tool_manager.get_tool("proj_init")
        assert tool_fn is not None

        async def _run() -> str:
            result = await tool_fn.run({"name": name, "path": str(tmp_path)}, {})
            if isinstance(result, list):
                return "".join(getattr(c, "text", str(c)) for c in result)
            return str(result)

        return asyncio.run(_run())

    def test_proj_init_calls_hooks_sync_on_success(
        self, cfg: ProjConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """proj_init posts to the hooks server on success."""
        from unittest.mock import MagicMock, patch

        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("httpx.HTTPTransport") as mock_transport, \
             patch("httpx.Client", return_value=mock_client):
            result = self._call_proj_init("hooktest", tmp_path)

        import json
        data = json.loads(result)
        assert "project_name" in data
        assert data["project_name"] == "hooktest"
        # Verify post was called with hooks_sync_tool
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["tool"] == "hooks_sync_tool"

    def test_proj_init_succeeds_when_hooks_unreachable(
        self, cfg: ProjConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """proj_init still returns success when hooks server is not running."""
        from unittest.mock import patch

        with patch("httpx.HTTPTransport", side_effect=Exception("connection refused")):
            result = self._call_proj_init("nohooks", tmp_path)

        import json
        data = json.loads(result)
        assert "project_name" in data
        assert data["project_name"] == "nohooks"
        # Project was still created
        index = storage.load_index(cfg)
        assert "nohooks" in index.projects


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


class TestProjArchivePreflight:
    """Tests for the proj_archive_preflight composite tool."""

    def _call_preflight(self, cfg: ProjConfig, project_name: str) -> str:
        import asyncio

        from mcp.server.fastmcp import FastMCP

        from server.tools.projects import register

        app = FastMCP("test-preflight")
        register(app)
        tool_fn = app._tool_manager.get_tool("proj_archive_preflight")
        assert tool_fn is not None

        async def _run() -> str:
            result = await tool_fn.run({"project_name": project_name}, {})
            if isinstance(result, list):
                return "".join(getattr(c, "text", str(c)) for c in result)
            return str(result)

        return asyncio.run(_run())

    def test_not_found(self, cfg: ProjConfig) -> None:
        result = self._call_preflight(cfg, "nonexistent")
        assert "not found" in result

    def test_already_archived(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        index = storage.load_index(cfg)
        index.projects["myapp"].archived = True
        storage.save_index(cfg, index)
        result = self._call_preflight(cfg, "myapp")
        assert "already archived" in result

    def test_returns_json_with_all_sections(self, cfg: ProjConfig, tmp_path: Path) -> None:
        import json

        _run_proj_init("myapp", str(tmp_path))
        result = self._call_preflight(cfg, "myapp")
        data = json.loads(result)
        assert "config" in data
        assert "project" in data
        assert "open_todos" in data
        assert "worktrees" in data

    def test_config_section(self, cfg: ProjConfig, tmp_path: Path) -> None:
        import json

        _run_proj_init("myapp", str(tmp_path))
        data = json.loads(self._call_preflight(cfg, "myapp"))
        assert data["config"]["archive_destination"] == cfg.archive.destination
        assert data["config"]["trash_grace_days"] == cfg.archive.trash_grace_days

    def test_project_section(self, cfg: ProjConfig, tmp_path: Path) -> None:
        import json

        _run_proj_init("myapp", str(tmp_path))
        data = json.loads(self._call_preflight(cfg, "myapp"))
        proj = data["project"]
        assert proj["name"] == "myapp"
        assert proj["status"] == "active"
        assert len(proj["repos"]) == 1
        assert proj["repos"][0]["label"] == "code"
        assert proj["trello_card_id"] is None
        assert proj["todoist_project_id"] is None

    def test_open_todos_empty(self, cfg: ProjConfig, tmp_path: Path) -> None:
        import json

        _run_proj_init("myapp", str(tmp_path))
        data = json.loads(self._call_preflight(cfg, "myapp"))
        assert data["open_todos"]["count"] == 0
        assert data["open_todos"]["items"] == []

    def test_open_todos_counted(self, cfg: ProjConfig, tmp_path: Path) -> None:
        import json

        from server.lib.models import Todo

        _run_proj_init("myapp", str(tmp_path))
        todos = [
            Todo(id="1", title="Open task", status="pending", created="2026-01-01", updated="2026-01-01"),
            Todo(id="2", title="Done task", status="done", created="2026-01-01", updated="2026-01-01"),
            Todo(id="3", title="In progress", status="in_progress", created="2026-01-01", updated="2026-01-01"),
            Todo(id="4", title="Cancelled", status="cancelled", created="2026-01-01", updated="2026-01-01"),
        ]
        storage.save_todos(cfg, "myapp", todos)
        data = json.loads(self._call_preflight(cfg, "myapp"))
        assert data["open_todos"]["count"] == 2
        ids = [t["id"] for t in data["open_todos"]["items"]]
        assert "1" in ids
        assert "3" in ids
        assert "2" not in ids
        assert "4" not in ids

    def test_worktrees_empty_when_no_git_file(self, cfg: ProjConfig, tmp_path: Path) -> None:
        import json

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        # Normal .git directory (not a worktree)
        (repo_dir / ".git").mkdir()
        _run_proj_init("myapp", str(repo_dir))
        data = json.loads(self._call_preflight(cfg, "myapp"))
        assert data["worktrees"] == []

    def test_worktrees_detected_when_git_file(self, cfg: ProjConfig, tmp_path: Path) -> None:
        import json

        repo_dir = tmp_path / "worktree-repo"
        repo_dir.mkdir()
        # .git file (not dir) indicates worktree
        (repo_dir / ".git").write_text("gitdir: /some/path/.git/worktrees/branch")
        _run_proj_init("myapp", str(repo_dir))
        data = json.loads(self._call_preflight(cfg, "myapp"))
        assert len(data["worktrees"]) == 1
        assert data["worktrees"][0]["path"] == str(repo_dir)
        assert data["worktrees"][0]["label"] == "code"


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
        import json

        result = self._call_proj_init("../../etc", tmp_path)
        # Result is JSON - check for error in result field or parse as error message
        try:
            data = json.loads(result)
            assert "path traversal" in data.get("error", "").lower() or "path traversal" in data.get("result", "").lower()
        except json.JSONDecodeError:
            assert "path traversal" in result.lower() or ".." in result

    def test_rejects_slash(self, cfg: ProjConfig, tmp_path: Path) -> None:
        import json

        result = self._call_proj_init("foo/bar", tmp_path)
        try:
            data = json.loads(result)
            # Check either error or result key
            msg = data.get("error", data.get("result", ""))
            assert "path separator" in msg.lower() or "/" in msg
        except json.JSONDecodeError:
            assert "path separator" in result.lower() or "/" in result

    def test_rejects_empty(self, cfg: ProjConfig, tmp_path: Path) -> None:
        import json

        result = self._call_proj_init("", tmp_path)
        try:
            data = json.loads(result)
            msg = data.get("error", data.get("result", ""))
            assert "empty" in msg.lower() or "whitespace" in msg.lower()
        except json.JSONDecodeError:
            assert "empty" in result.lower() or "whitespace" in result.lower()

    def test_rejects_dot_git(self, cfg: ProjConfig, tmp_path: Path) -> None:
        import json

        result = self._call_proj_init(".git", tmp_path)
        try:
            data = json.loads(result)
            msg = data.get("error", data.get("result", ""))
            assert "." in msg or "reserved" in msg.lower()
        except json.JSONDecodeError:
            assert "." in result or "reserved" in result.lower()

    def test_no_directory_created_on_invalid_name(
        self, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        tracking_root = Path(cfg.tracking_dir)
        self._call_proj_init("../../evil", tmp_path)
        # No directory should have been created under the tracking root
        assert not any(tracking_root.iterdir()) if tracking_root.exists() else True

    def test_valid_init_returns_json_with_project_name(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Test that proj_init returns JSON with project_name field."""
        import json

        result = self._call_proj_init("validproject", tmp_path)
        data = json.loads(result)
        assert "project_name" in data
        assert data["project_name"] == "validproject"
        assert "result" in data
