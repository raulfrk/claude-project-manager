"""Tests for project CRUD tools."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import ProjConfig, ProjectEntry, Todo, validate_project_name


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
        # todos.yaml is migrated to SQLite (todos.yaml.bak) immediately after init;
        # verify todos are accessible via storage instead
        from server.lib import storage as _st

        todos = _st.load_todos(cfg, "myapp")
        assert isinstance(todos, list)


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

        with (
            patch(
                "server.tools.projects._resolve_router_socket_path", return_value="/tmp/fake.sock"
            ),
            patch("httpx.HTTPTransport"),
            patch("httpx.Client", return_value=mock_client),
        ):
            result = self._call_proj_init("hooktest", tmp_path)

        import json

        data = json.loads(result)
        assert "project_name" in data
        assert data["project_name"] == "hooktest"
        # Verify post was called with router_sync_tool
        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        assert call_args[1]["json"]["tool"] == "router_sync_tool"

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

    @pytest.mark.parametrize(
        "name",
        ["myproject", "my-project-123", "my_project", "MyProject"],
    )
    def test_valid_names(self, name: str) -> None:
        assert validate_project_name(name) is None

    # --- empty / whitespace -------------------------------------------------

    @pytest.mark.parametrize("name", ["", "   ", "\t"])
    def test_empty_or_whitespace(self, name: str) -> None:
        assert validate_project_name(name) is not None

    # --- path traversal -----------------------------------------------------

    def test_double_dot(self) -> None:
        assert validate_project_name("../../etc") is not None

    def test_double_dot_suffix(self) -> None:
        assert validate_project_name("foo..bar") is not None

    # --- path separators / null byte ----------------------------------------

    @pytest.mark.parametrize("name", ["foo/bar", "foo\\bar", "foo\x00bar"])
    def test_path_separators_and_null(self, name: str) -> None:
        assert validate_project_name(name) is not None

    # --- dot-prefixed / reserved --------------------------------------------

    def test_dot_git(self) -> None:
        assert validate_project_name(".git") is not None

    def test_dot_hidden(self) -> None:
        assert validate_project_name(".hidden") is not None

    def test_single_dot(self) -> None:
        assert validate_project_name(".") is not None

    # --- control characters -------------------------------------------------

    @pytest.mark.parametrize("name", ["foo\nbar", "foo\rbar", "foo\x7fbar", "foo\x01bar"])
    def test_control_characters(self, name: str) -> None:
        assert validate_project_name(name) is not None

    # --- unicode ------------------------------------------------------------

    @pytest.mark.parametrize("name", ["projet-été", "プロジェクト", "project-2024-café"])
    def test_valid_unicode(self, name: str) -> None:
        assert validate_project_name(name) is None

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

    @pytest.mark.parametrize("name", ["...", "..hidden", ".."])
    def test_double_dot_patterns(self, name: str) -> None:
        assert validate_project_name(name) is not None

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

        _run_proj_init("myapp", str(tmp_path))
        todos = [
            Todo(
                id="1",
                title="Open task",
                status="pending",
                created="2026-01-01",
                updated="2026-01-01",
            ),
            Todo(
                id="2", title="Done task", status="done", created="2026-01-01", updated="2026-01-01"
            ),
            Todo(
                id="3",
                title="In progress",
                status="in_progress",
                created="2026-01-01",
                updated="2026-01-01",
            ),
            Todo(
                id="4",
                title="Cancelled",
                status="cancelled",
                created="2026-01-01",
                updated="2026-01-01",
            ),
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
            assert (
                "path traversal" in data.get("error", "").lower()
                or "path traversal" in data.get("result", "").lower()
            )
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

    def test_no_directory_created_on_invalid_name(self, cfg: ProjConfig, tmp_path: Path) -> None:
        tracking_root = Path(cfg.tracking_dir)
        self._call_proj_init("../../evil", tmp_path)
        # No directory should have been created under the tracking root
        assert not any(tracking_root.iterdir()) if tracking_root.exists() else True

    def test_valid_init_returns_json_with_project_name(
        self, cfg: ProjConfig, tmp_path: Path
    ) -> None:
        """Test that proj_init returns JSON with project_name field."""
        import json

        result = self._call_proj_init("validproject", tmp_path)
        data = json.loads(result)
        assert "project_name" in data
        assert data["project_name"] == "validproject"
        assert "result" in data


# ── Helpers ──────────────────────────────────────────────────────────────────


def _get_tools() -> dict[str, Callable[..., Any]]:
    """Register all project tools and return a name->fn dict (sync wrappers)."""
    from mcp.server.fastmcp import FastMCP

    from server.tools.projects import register

    app = FastMCP("test-tools")
    register(app)
    tools: dict[str, Callable[..., Any]] = {}
    for name in app._tool_manager._tools:
        tool_obj = app._tool_manager.get_tool(name)
        if tool_obj is None:
            continue

        def _make_sync(t: Any = tool_obj) -> Callable[..., str]:
            def _call(**kwargs: Any) -> str:
                result = asyncio.run(t.run(kwargs, {}))
                if isinstance(result, list):
                    return "".join(getattr(c, "text", str(c)) for c in result)
                return str(result)

            return _call

        tools[name] = _make_sync()
    return tools


# ── TestProjList ─────────────────────────────────────────────────────────────


class TestProjList:
    def test_no_projects(self, cfg: ProjConfig) -> None:
        tools = _get_tools()
        result = tools["proj_list"]()
        assert "No projects found" in result

    def test_lists_created_project(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        result = tools["proj_list"]()
        assert "myapp" in result

    def test_excludes_archived_by_default(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        index = storage.load_index(cfg)
        index.projects["myapp"].archived = True
        storage.save_index(cfg, index)
        tools = _get_tools()
        result = tools["proj_list"]()
        assert "No projects found" in result

    def test_includes_archived_when_requested(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        index = storage.load_index(cfg)
        index.projects["myapp"].archived = True
        storage.save_index(cfg, index)
        tools = _get_tools()
        result = tools["proj_list"](include_archived=True)
        assert "myapp" in result


# ── TestProjListFull ─────────────────────────────────────────────────────────


class TestProjListFull:
    def test_empty_projects(self, cfg: ProjConfig) -> None:
        tools = _get_tools()
        data = json.loads(tools["proj_list_full"]())
        assert data["count"] == 0
        assert data["projects"] == []

    def test_returns_project_metadata(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        data = json.loads(tools["proj_list_full"]())
        assert data["count"] == 1
        assert data["projects"][0]["name"] == "myapp"
        assert "repos" in data["projects"][0]

    def test_invalid_integration_filter(self, cfg: ProjConfig) -> None:
        tools = _get_tools()
        data = json.loads(tools["proj_list_full"](integration_filter="invalid"))
        assert "error" in data


# ── TestProjGet ──────────────────────────────────────────────────────────────


class TestProjGet:
    def test_no_active_project(self, cfg: ProjConfig) -> None:
        state.clear_session_active()
        tools = _get_tools()
        data = json.loads(tools["proj_get"]())
        assert "error" in data

    def test_returns_project_details(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        data = json.loads(tools["proj_get"](name="myapp"))
        assert data["name"] == "myapp"

    def test_not_found(self, cfg: ProjConfig) -> None:
        tools = _get_tools()
        data = json.loads(tools["proj_get"](name="nonexistent"))
        assert "error" in data


# ── TestProjGetActive ────────────────────────────────────────────────────────


class TestProjGetActive:
    def test_no_active(self, cfg: ProjConfig) -> None:
        state.clear_session_active()
        tools = _get_tools()
        data = json.loads(tools["proj_get_active"]())
        assert "error" in data

    def test_returns_active_project(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        state.set_session_active("myapp")
        tools = _get_tools()
        result = tools["proj_get_active"]()
        data = json.loads(result)
        assert "error" not in data, f"Unexpected error: {data}"
        assert data["name"] == "myapp"


# ── TestProjUpdateMeta ───────────────────────────────────────────────────────


class TestProjUpdateMeta:
    def test_update_description(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        data = json.loads(tools["proj_update_meta"](name="myapp", description="New desc"))
        assert "Updated" in data["result"]
        meta = storage.load_meta(cfg, "myapp")
        assert meta.description == "New desc"

    def test_update_status(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        data = json.loads(tools["proj_update_meta"](name="myapp", status="paused"))
        assert "Updated" in data["result"]
        meta = storage.load_meta(cfg, "myapp")
        assert meta.status == "paused"

    def test_update_multiple_fields(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        tools["proj_update_meta"](
            name="myapp",
            priority="high",
            tags=["backend", "urgent"],
            target_date="2026-12-31",
        )
        meta = storage.load_meta(cfg, "myapp")
        assert meta.priority == "high"
        assert meta.tags == ["backend", "urgent"]
        assert meta.dates.target == "2026-12-31"

    def test_not_found(self, cfg: ProjConfig) -> None:
        tools = _get_tools()
        data = json.loads(tools["proj_update_meta"](name="nonexistent", description="x"))
        assert data["status"] == "not_found"


# ── TestProjArchive ──────────────────────────────────────────────────────────


class TestProjArchive:
    def test_archives_project(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        data = json.loads(tools["proj_archive"](name="myapp"))
        assert "Archived" in data["result"]
        index = storage.load_index(cfg)
        assert index.projects["myapp"].archived is True

    def test_clears_session_active(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        state.set_session_active("myapp")
        tools = _get_tools()
        tools["proj_archive"](name="myapp")
        assert state.get_session_active() is None

    def test_not_found(self, cfg: ProjConfig) -> None:
        tools = _get_tools()
        data = json.loads(tools["proj_archive"](name="nonexistent"))
        assert "error" in data


# ── TestProjAddRepo ──────────────────────────────────────────────────────────


class TestProjAddRepo:
    def test_adds_repo(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        new_repo = tmp_path / "extra"
        new_repo.mkdir()
        tools = _get_tools()
        data = json.loads(
            tools["proj_add_repo"](repo_path=str(new_repo), label="extra", project_name="myapp")
        )
        assert "Added" in data["result"]
        meta = storage.load_meta(cfg, "myapp")
        assert len(meta.repos) == 2
        assert meta.repos[1].label == "extra"

    def test_duplicate_path_rejected(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        data = json.loads(
            tools["proj_add_repo"](repo_path=str(tmp_path), label="dupe", project_name="myapp")
        )
        assert "error" in data
        assert "already registered" in data["error"]

    def test_duplicate_label_rejected(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        other = tmp_path / "other"
        other.mkdir()
        tools = _get_tools()
        data = json.loads(
            tools["proj_add_repo"](repo_path=str(other), label="code", project_name="myapp")
        )
        assert "error" in data
        assert "Label" in data["error"]

    def test_nonexistent_path_rejected(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        data = json.loads(
            tools["proj_add_repo"](repo_path="/nonexistent/path", label="bad", project_name="myapp")
        )
        assert "error" in data


# ── TestProjRemoveRepo ───────────────────────────────────────────────────────


class TestProjRemoveRepo:
    def test_removes_repo(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        extra = tmp_path / "extra"
        extra.mkdir()
        tools = _get_tools()
        tools["proj_add_repo"](repo_path=str(extra), label="extra", project_name="myapp")
        data = json.loads(tools["proj_remove_repo"](label="extra", project_name="myapp"))
        assert "Removed" in data["result"]
        meta = storage.load_meta(cfg, "myapp")
        assert len(meta.repos) == 1

    def test_cannot_remove_last_repo(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        data = json.loads(tools["proj_remove_repo"](label="code", project_name="myapp"))
        assert "error" in data
        assert "last repo" in data["error"]

    def test_label_not_found(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        data = json.loads(tools["proj_remove_repo"](label="nope", project_name="myapp"))
        assert "error" in data


# ── TestProjLoadSession ──────────────────────────────────────────────────────


class TestProjLoadSession:
    def test_loads_project(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        state.clear_session_active()
        tools = _get_tools()
        data = json.loads(tools["proj_load_session"](name="myapp"))
        assert data["project_name"] == "myapp"
        assert state.get_session_active() == "myapp"

    def test_not_found_suggests(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        data = json.loads(tools["proj_load_session"](name="myap"))
        # Fuzzy match should auto-resolve to "myapp"
        assert data["project_name"] == "myapp"

    def test_not_found_no_match(self, cfg: ProjConfig) -> None:
        tools = _get_tools()
        data = json.loads(tools["proj_load_session"](name="zzz_nonexistent"))
        assert "error" in data


# ── TestProjSetPermissions ───────────────────────────────────────────────────


class TestProjSetPermissions:
    def test_set_auto_grant(self, cfg: ProjConfig, tmp_path: Path) -> None:
        _run_proj_init("myapp", str(tmp_path))
        tools = _get_tools()
        data = json.loads(tools["proj_set_permissions"](auto_grant=True, project_name="myapp"))
        assert "Set permissions" in data["result"]
        meta = storage.load_meta(cfg, "myapp")
        assert meta.permissions.auto_grant is True


# ── TestProjInitDirs ────────────────────────────────────────────────────────


class TestProjInitDirs:
    """Integration tests: proj_init with the dirs parameter (multi-directory)."""

    def _call_proj_init(self, tmp_path: Path, **kwargs: Any) -> str:
        from mcp.server.fastmcp import FastMCP

        from server.tools.projects import register

        app = FastMCP("test-dirs")
        register(app)
        tool_fn = app._tool_manager.get_tool("proj_init")
        assert tool_fn is not None

        async def _run() -> str:
            result = await tool_fn.run(kwargs, {})
            if isinstance(result, list):
                return "".join(getattr(c, "text", str(c)) for c in result)
            return str(result)

        return asyncio.run(_run())

    def test_dirs_creates_multi_repo_project(self, cfg: ProjConfig, tmp_path: Path) -> None:
        dir1 = tmp_path / "frontend"
        dir2 = tmp_path / "backend"
        dir1.mkdir()
        dir2.mkdir()
        result = self._call_proj_init(
            tmp_path,
            name="multi-repo",
            dirs=[
                {"path": str(dir1), "label": "frontend"},
                {"path": str(dir2), "label": "backend"},
            ],
        )
        data = json.loads(result)
        assert "project_name" in data
        assert data["project_name"] == "multi-repo"
        meta = storage.load_meta(cfg, "multi-repo")
        assert len(meta.repos) == 2
        labels = {r.label for r in meta.repos}
        assert labels == {"frontend", "backend"}

    def test_dirs_and_path_mutually_exclusive(self, cfg: ProjConfig, tmp_path: Path) -> None:
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        result = self._call_proj_init(
            tmp_path,
            name="conflict",
            path=str(dir1),
            dirs=[{"path": str(dir1), "label": "code"}],
        )
        data = json.loads(result)
        assert "error" in data
        assert "either" in data["error"].lower() or "not both" in data["error"].lower()

    def test_dirs_duplicate_label_rejected(self, cfg: ProjConfig, tmp_path: Path) -> None:
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        dir1.mkdir()
        dir2.mkdir()
        result = self._call_proj_init(
            tmp_path,
            name="dup-label",
            dirs=[{"path": str(dir1), "label": "code"}, {"path": str(dir2), "label": "code"}],
        )
        data = json.loads(result)
        assert "error" in data
        assert "Duplicate label" in data["error"]

    def test_dirs_missing_path_rejected(self, cfg: ProjConfig, tmp_path: Path) -> None:
        result = self._call_proj_init(
            tmp_path,
            name="missing-path",
            dirs=[{"path": "", "label": "code"}],
        )
        data = json.loads(result)
        assert "error" in data
        assert "path" in data["error"].lower()

    def test_dirs_missing_label_rejected(self, cfg: ProjConfig, tmp_path: Path) -> None:
        dir1 = tmp_path / "dir1"
        dir1.mkdir()
        result = self._call_proj_init(
            tmp_path,
            name="missing-label",
            dirs=[{"path": str(dir1), "label": ""}],
        )
        data = json.loads(result)
        assert "error" in data
        assert "label" in data["error"].lower()


# ── TestProjInitProjectsBaseDir ─────────────────────────────────────────────


class TestProjInitProjectsBaseDir:
    """Integration tests: proj_init fallback to projects_base_dir when no path given."""

    def _call_proj_init(self, **kwargs: Any) -> str:
        from mcp.server.fastmcp import FastMCP

        from server.tools.projects import register

        app = FastMCP("test-base-dir")
        register(app)
        tool_fn = app._tool_manager.get_tool("proj_init")
        assert tool_fn is not None

        async def _run() -> str:
            result = await tool_fn.run(kwargs, {})
            if isinstance(result, list):
                return "".join(getattr(c, "text", str(c)) for c in result)
            return str(result)

        return asyncio.run(_run())

    def test_no_path_no_base_dir_returns_error(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """No path and no projects_base_dir configured returns an error."""
        # Default cfg has no projects_base_dir
        result = self._call_proj_init(name="no-path-proj")
        data = json.loads(result)
        assert "error" in data
        assert "projects_base_dir" in data["error"]

    def test_projects_base_dir_fallback(
        self, cfg: ProjConfig, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When projects_base_dir is set and no path given, uses base_dir/name."""
        base_dir = tmp_path / "projects"
        base_dir.mkdir()

        # Update config with projects_base_dir
        cfg_obj = storage.load_config()
        cfg_obj.projects_base_dir = str(base_dir)
        storage.save_config(cfg_obj)

        result = self._call_proj_init(name="auto-path-proj")
        data = json.loads(result)
        assert "project_name" in data
        assert data["project_name"] == "auto-path-proj"
        # Verify the repo path was derived from projects_base_dir
        meta = storage.load_meta(cfg, "auto-path-proj")
        assert len(meta.repos) == 1
        expected_path = str((base_dir / "auto-path-proj").resolve())
        assert meta.repos[0].path == expected_path
        assert meta.repos[0].label == "code"


# ── TestProjPurgeArchiveTool ────────────────────────────────────────────────


class TestProjPurgeArchiveTool:
    """Tests for proj_purge_archive using direct tool registration."""

    def _call_purge(self, **kwargs: Any) -> str:
        from mcp.server.fastmcp import FastMCP

        from server.tools.projects import register

        app = FastMCP("test-purge")
        register(app)
        tool_fn = app._tool_manager.get_tool("proj_purge_archive")
        assert tool_fn is not None

        async def _run() -> str:
            result = await tool_fn.run(kwargs, {})
            if isinstance(result, list):
                return "".join(getattr(c, "text", str(c)) for c in result)
            return str(result)

        return asyncio.run(_run())

    def test_purge_not_configured(self, cfg: ProjConfig) -> None:
        """When purge_after_days is None, returns not-configured error."""
        result = json.loads(self._call_purge())
        assert "error" in result
        assert "not configured" in result["error"].lower()

    def test_purge_dry_run_lists_candidates(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Dry-run (confirm=False) lists eligible candidates without deleting."""
        from datetime import timedelta

        # Configure purge
        cfg_obj = storage.load_config()
        cfg_obj.archive.purge_after_days = 30
        storage.save_config(cfg_obj)

        # Create an archived project with old archive_date
        _run_proj_init("old-proj", str(tmp_path / "old"))
        index = storage.load_index(cfg)
        entry = index.projects["old-proj"]
        entry.archived = True
        entry.purgeable = True
        from datetime import date

        entry.archive_date = (date.today() - timedelta(days=60)).isoformat()
        storage.save_index(cfg, index)

        result = json.loads(self._call_purge())
        assert result.get("dry_run") is True
        assert result["count"] == 1
        assert result["candidates"][0]["name"] == "old-proj"

    def test_purge_confirm_deletes(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """confirm=True actually purges eligible projects."""
        from datetime import timedelta

        cfg_obj = storage.load_config()
        cfg_obj.archive.purge_after_days = 30
        storage.save_config(cfg_obj)

        _run_proj_init("doomed", str(tmp_path / "doomed"))
        index = storage.load_index(cfg)
        entry = index.projects["doomed"]
        entry.archived = True
        entry.purgeable = True
        from datetime import date

        entry.archive_date = (date.today() - timedelta(days=60)).isoformat()
        storage.save_index(cfg, index)

        tracking_dir = Path(cfg.tracking_dir) / "doomed"
        assert tracking_dir.exists()

        result = json.loads(self._call_purge(confirm=True))
        assert "doomed" in result.get("purged", [])
        assert not tracking_dir.exists()
        index = storage.load_index(cfg)
        assert "doomed" not in index.projects

    def test_purge_skips_non_purgeable(self, cfg: ProjConfig, tmp_path: Path) -> None:
        """Archived project with purgeable=False is not purged."""
        from datetime import timedelta

        cfg_obj = storage.load_config()
        cfg_obj.archive.purge_after_days = 30
        storage.save_config(cfg_obj)

        _run_proj_init("protected", str(tmp_path / "protected"))
        index = storage.load_index(cfg)
        entry = index.projects["protected"]
        entry.archived = True
        entry.purgeable = False
        from datetime import date

        entry.archive_date = (date.today() - timedelta(days=60)).isoformat()
        storage.save_index(cfg, index)

        result = json.loads(self._call_purge())
        candidates = [c["name"] for c in result.get("candidates", [])]
        assert "protected" not in candidates

    def test_purge_no_candidates(self, cfg: ProjConfig) -> None:
        """When no projects are eligible, returns empty result."""
        cfg_obj = storage.load_config()
        cfg_obj.archive.purge_after_days = 30
        storage.save_config(cfg_obj)

        result = json.loads(self._call_purge())
        assert "No projects eligible" in result.get("result", "")
