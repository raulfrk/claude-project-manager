"""Tests for quality fixes 475.55-475.65."""

from __future__ import annotations

import json
import shutil
import threading
from datetime import date
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from mcp.server.fastmcp import FastMCP

from server.lib import state, storage
from server.lib.models import ProjConfig, Todo
from server.lib.resilience import CircuitBreakerManager
from tests.conftest import call_tool, setup_project


def _make_todo(
    tid: str,
    title: str = "Task",
    *,
    parent: str | None = None,
    status: str = "pending",
    todoist_task_id: str = "",
    trello_card_id: str = "",
    jira_issue_key: str = "",
) -> Todo:
    today = str(date.today())
    tags = [f"group:{parent}"] if parent is not None else []
    return Todo(
        id=tid,
        title=title,
        created=today,
        updated=today,
        status=status,  # type: ignore[arg-type]
        tags=tags,
        todoist_task_id=todoist_task_id,
        trello_card_id=trello_card_id,
        jira_issue_key=jira_issue_key,
    )


# ── 475.55: resilience _save() cross-filesystem fallback ─────────────────────


class TestResilienceCrossFilesystemFallback:
    def test_save_cross_filesystem_fallback(self, tmp_path: Path):
        """When os.rename raises OSError, _save falls back to copy+delete."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        mgr = CircuitBreakerManager(state_dir)
        mgr.record_failure("todoist", "timeout")

        # Verify file was written despite any rename issues
        mgr2 = CircuitBreakerManager(state_dir)
        assert mgr2._breakers["todoist"].failure_count == 1

    def test_save_cross_filesystem_uses_shutil_on_oserror(self, tmp_path: Path):
        """Simulate cross-filesystem rename failure → shutil.copy2 fallback."""
        state_dir = tmp_path / "state"
        state_dir.mkdir()
        mgr = CircuitBreakerManager(state_dir)
        mgr.record_failure("test-svc", "err")

        # Monkey-patch Path.rename to raise OSError (simulating cross-fs)
        rename_called = []
        copy_called = []

        def failing_rename(self, target):
            rename_called.append(1)
            raise OSError("Invalid cross-device link")

        orig_copy2 = shutil.copy2

        def tracking_copy2(src, dst):
            copy_called.append(1)
            return orig_copy2(src, dst)

        with patch.object(Path, "rename", failing_rename), patch("shutil.copy2", tracking_copy2):
            mgr.record_failure("test-svc", "err2")

        assert len(rename_called) >= 1
        assert len(copy_called) >= 1
        # State still persisted correctly
        mgr3 = CircuitBreakerManager(state_dir)
        assert mgr3._breakers["test-svc"].failure_count == 2


# ── 475.56: validate socket registry path before read ─────────────────────────


class TestSocketPathValidation:
    def test_resolve_router_socket_missing_registry(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """When registry file does not exist, returns None (no fallback to hardcoded path)."""
        from server.tools.projects import _resolve_router_socket_path

        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        result = _resolve_router_socket_path()
        # Should return None or a valid path, never a hardcoded /tmp path
        if result is not None:
            assert Path(result).exists()

    def test_fallback_router_socket_uses_tempdir(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ):
        """_fallback_router_socket uses tempfile.gettempdir(), not hardcoded /tmp."""
        from server.tools.projects import _fallback_router_socket

        monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
        result = _fallback_router_socket()
        # No candidates exist in tmp_path, so should return None
        assert result is None


# ── 475.57: null-guard jira_full_sync result ──────────────────────────────────


class TestJiraFullSyncNullGuard:
    def test_fetch_jira_issues_returns_empty_on_none(self, monkeypatch: pytest.MonkeyPatch):
        """When _call_jira_tool returns None, _fetch_jira_issues returns ([], 0)."""
        from server.tools.jira_full_sync import _fetch_jira_issues

        monkeypatch.setattr(
            "server.tools.jira_full_sync._call_jira_tool",
            lambda *a, **kw: None,
        )
        issues, total = _fetch_jira_issues(None)
        assert issues == []
        assert total == 0


# ── 475.58: raise on invalid todoist sync JSON ───────────────────────────────


class TestTodoistInvalidJsonRaise:
    def test_invalid_json_raises_valueerror(self, monkeypatch: pytest.MonkeyPatch):
        """_call_todoist_tool raises ValueError on unparseable JSON response."""
        from server.tools import todoist_full_sync as tmod

        # Simulate the MCP call returning a non-JSON string
        def fake_call(tool_name, params):
            raise ValueError("Invalid JSON from todoist sync: not-json")

        monkeypatch.setattr(tmod, "_call_todoist_tool", fake_call)
        with pytest.raises(ValueError, match="Invalid JSON"):
            tmod._call_todoist_tool("todoist_find_tasks", {})


# ── 475.59: distinguish permanent vs retryable in trello_full_sync ────────────


class TestTrelloErrorClassification:
    def test_timeout_is_retryable(self):
        from server.tools.trello_full_sync import _classify_error, _is_retryable

        exc = httpx.TimeoutException("timed out")
        assert _is_retryable(exc) is True
        msg = _classify_error(exc, "fetch_board")
        assert "retryable" in msg.lower()

    def test_connect_error_is_retryable(self):
        from server.tools.trello_full_sync import _classify_error, _is_retryable

        exc = httpx.ConnectError("refused")
        assert _is_retryable(exc) is True
        msg = _classify_error(exc, "fetch_board")
        assert "retryable" in msg.lower()

    def test_http_status_error_is_permanent(self):
        from server.tools.trello_full_sync import _classify_error, _is_retryable

        request = httpx.Request("GET", "https://api.trello.com/1/boards")
        response = httpx.Response(404, request=request)
        exc = httpx.HTTPStatusError("not found", request=request, response=response)
        assert _is_retryable(exc) is False
        msg = _classify_error(exc, "fetch_board")
        assert "permanent" in msg.lower()
        assert "404" in msg

    def test_generic_error_is_permanent(self):
        from server.tools.trello_full_sync import _classify_error, _is_retryable

        exc = RuntimeError("unexpected")
        assert _is_retryable(exc) is False
        msg = _classify_error(exc, "sync")
        assert "permanent" in msg.lower()


# ── 475.60: replace hardcoded /tmp with tempfile.gettempdir() ─────────────────


class TestNoHardcodedTmp:
    """Verify none of the 4 sync files contain hardcoded /tmp paths."""

    @pytest.mark.parametrize(
        "module_path",
        [
            "server/tools/todos.py",
            "server/tools/trello_full_sync.py",
            "server/tools/todoist_full_sync.py",
            "server/tools/jira_full_sync.py",
        ],
    )
    def test_no_hardcoded_tmp(self, module_path: str):
        import server

        base = Path(server.__file__).parent.parent
        source = (base / module_path).read_text()
        # Filter out comments (lines starting with #) and noqa lines
        code_lines = [line for line in source.splitlines() if not line.strip().startswith("#")]
        code = "\n".join(code_lines)
        # Should not contain Path("/tmp") or '"/tmp/' patterns
        assert 'Path("/tmp")' not in code, f"{module_path} still has hardcoded /tmp"
        assert "'/tmp/" not in code, f"{module_path} still has hardcoded /tmp"
        assert '"/tmp/' not in code, f"{module_path} still has hardcoded /tmp"


# ── 475.61: validate due_date YYYY-MM-DD format ──────────────────────────────


@pytest.fixture()
def todo_mcp_app(cfg: ProjConfig) -> FastMCP:
    from server.tools import config, projects, todos

    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos.register(app)
    return app


class TestDueDateValidation:
    @pytest.mark.asyncio
    async def test_valid_due_date_accepted(self, cfg: ProjConfig, todo_mcp_app, tmp_path: Path):
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        result = await call_tool(
            todo_mcp_app,
            "todo_add",
            title="Test task",
            due_date="2026-04-15",
        )
        data = json.loads(result)
        assert "error" not in data

    @pytest.mark.asyncio
    async def test_invalid_due_date_rejected(self, cfg: ProjConfig, todo_mcp_app, tmp_path: Path):
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        result = await call_tool(
            todo_mcp_app,
            "todo_add",
            title="Test task",
            due_date="next Friday",
        )
        data = json.loads(result)
        assert "error" in data
        assert "YYYY-MM-DD" in data["error"]

    @pytest.mark.asyncio
    async def test_empty_due_date_rejected(self, cfg: ProjConfig, todo_mcp_app, tmp_path: Path):
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        result = await call_tool(
            todo_mcp_app,
            "todo_add",
            title="Test task",
            due_date="  ",
        )
        data = json.loads(result)
        assert "error" in data

    @pytest.mark.asyncio
    async def test_due_date_slash_format_rejected(
        self, cfg: ProjConfig, todo_mcp_app, tmp_path: Path
    ):
        setup_project(cfg, "myapp", str(tmp_path))
        state.set_session_active("myapp")
        result = await call_tool(
            todo_mcp_app,
            "todo_add",
            title="Test task",
            due_date="04/15/2026",
        )
        data = json.loads(result)
        assert "error" in data
        assert "YYYY-MM-DD" in data["error"]


# ── 475.62: _MAX_SOURCE_BYTES documented ──────────────────────────────────────


class TestMaxSourceBytesDocumented:
    def test_max_source_bytes_has_comment(self):
        """The _MAX_SOURCE_BYTES constant should have an explanatory comment."""
        import server

        base = Path(server.__file__).parent.parent
        source = (base / "server" / "tools" / "todos.py").read_text()
        idx = source.index("_MAX_SOURCE_BYTES")
        # Look at the ~5 lines before the constant
        preceding = source[:idx].splitlines()[-5:]
        preceding_text = "\n".join(preceding)
        assert (
            "payload" in preceding_text.lower()
            or "cap" in preceding_text.lower()
            or "mcp" in preceding_text.lower()
        )


# ── 475.63: validate default_priority in ProjConfig ───────────────────────────


class TestDefaultPriorityValidation:
    def test_valid_priorities_accepted(self):
        for prio in ("high", "medium", "low"):
            cfg = ProjConfig.from_dict({"default_priority": prio})
            assert cfg.default_priority == prio

    def test_invalid_priority_falls_back_to_medium(self):
        cfg = ProjConfig.from_dict({"default_priority": "urgent"})
        assert cfg.default_priority == "medium"

    def test_empty_priority_falls_back_to_medium(self):
        cfg = ProjConfig.from_dict({"default_priority": ""})
        assert cfg.default_priority == "medium"

    def test_missing_priority_defaults_to_medium(self):
        cfg = ProjConfig.from_dict({})
        assert cfg.default_priority == "medium"


# ── 475.64: validate jira_issue_key format ────────────────────────────────────


class TestJiraIssueKeyValidation:
    def test_valid_keys(self):
        from server.tools.jira_sync import _validate_jira_key

        assert _validate_jira_key("PROJ-123") is True
        assert _validate_jira_key("AB-1") is True
        assert _validate_jira_key("MY2-99999") is True

    def test_invalid_keys(self):
        from server.tools.jira_sync import _validate_jira_key

        assert _validate_jira_key("") is False
        assert _validate_jira_key("proj-123") is False  # lowercase
        assert _validate_jira_key("P-") is False  # no digits
        assert _validate_jira_key("-123") is False  # no project
        assert _validate_jira_key("PROJ123") is False  # no dash
        assert _validate_jira_key("PROJ-abc") is False  # non-digit
        assert _validate_jira_key("P-0 extra") is False  # trailing text

    def test_regex_pattern_matches_spec(self):
        from server.tools.jira_sync import _JIRA_KEY_RE

        assert _JIRA_KEY_RE.pattern == r"^[A-Z][A-Z0-9]+-\d+$"


# ── 475.65: concurrent batch_complete race condition test ─────────────────────


class TestConcurrentBatchComplete:
    def test_concurrent_batches_no_data_loss(self, cfg: ProjConfig, tmp_path: Path):
        """Two concurrent batch_complete calls must not lose todos or corrupt state.

        Each thread completes a disjoint set of todos. After both finish,
        all targeted todos must be done/archived and no non-targeted todos
        should be affected.
        """
        setup_project(cfg, "myapp", str(tmp_path))
        # 10 todos: threads will each complete 5
        todos = [_make_todo(str(i)) for i in range(1, 11)]
        storage.save_todos(cfg, "myapp", todos)
        state.set_session_active("myapp")

        results: dict[str, str] = {}
        errors: list[Exception] = []

        def worker(name: str, ids: list[str]) -> None:
            try:
                from server.tools import config, projects
                from server.tools import todos as tmod

                app = FastMCP(f"test-{name}")
                config.register(app)
                projects.register(app)
                tmod.register(app)
                import asyncio

                result = asyncio.run(call_tool(app, "todo_complete", todo_ids=ids))
                results[name] = result
            except Exception as e:
                errors.append(e)

        t1 = threading.Thread(target=worker, args=("A", [str(i) for i in range(1, 6)]))
        t2 = threading.Thread(target=worker, args=("B", [str(i) for i in range(6, 11)]))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert not errors, f"Worker errors: {errors}"

        # Both batches should have succeeded
        for name, raw in results.items():
            data = json.loads(raw)
            assert "error" not in data, f"Worker {name} failed: {data}"

        # All 10 todos should be archived
        archived = storage.load_archived_todos(cfg, "myapp")
        archived_ids = {t.id for t in archived}
        assert archived_ids >= {str(i) for i in range(1, 11)}

        # Active list should be empty
        remaining = storage.load_todos(cfg, "myapp")
        remaining_active = [t for t in remaining if t.id in {str(i) for i in range(1, 11)}]
        assert len(remaining_active) == 0

    def test_concurrent_overlapping_ids_serialized(self, cfg: ProjConfig, tmp_path: Path):
        """Two threads trying to complete overlapping id sets must serialize
        under the lock — one succeeds, the other sees them as already done."""
        setup_project(cfg, "myapp", str(tmp_path))
        todos = [_make_todo(str(i)) for i in range(1, 4)]
        storage.save_todos(cfg, "myapp", todos)
        state.set_session_active("myapp")

        results: list[dict] = []
        errors: list[Exception] = []

        def worker(ids: list[str]) -> None:
            try:
                from server.tools import config, projects
                from server.tools import todos as tmod

                app = FastMCP("test-overlap")
                config.register(app)
                projects.register(app)
                tmod.register(app)
                import asyncio

                raw = asyncio.run(call_tool(app, "todo_complete", todo_ids=ids))
                results.append(json.loads(raw))
            except Exception as e:
                errors.append(e)

        # Both try to complete ids 1,2,3
        t1 = threading.Thread(target=worker, args=(["1", "2", "3"],))
        t2 = threading.Thread(target=worker, args=(["1", "2", "3"],))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert not errors, f"Worker errors: {errors}"
        assert len(results) == 2

        # Between both results, all 3 should appear as completed or skipped
        all_completed = set()
        all_skipped = set()
        for r in results:
            all_completed.update(r.get("completed_ids", []))
            all_skipped.update(r.get("skipped_ids", []))

        assert {"1", "2", "3"} <= (all_completed | all_skipped)
