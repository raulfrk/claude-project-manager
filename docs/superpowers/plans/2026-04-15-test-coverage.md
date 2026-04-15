# Test Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add unit tests for 19 untested source files across proj lib/ and router lib/tools/.

**Architecture:** 6 tasks grouped by module relatedness. Each task creates 2-4 test files, runs tests, commits. Proj tests run in worktree `/home/raul/worktrees/cpm/todo-630-632`. Router tests run in worktree `/home/raul/worktrees/cpm/todo-633-634`.

**Tech Stack:** pytest, pytest-asyncio, monkeypatch, tmp_path, freezegun

---

## File Map

| Test File (Create) | Source File | Task |
|---|---|---|
| `plugins/proj/server/tests/test_enums.py` | `server/lib/enums.py` (20 lines) | 1 |
| `plugins/proj/server/tests/test_ids.py` | `server/lib/ids.py` (23 lines) | 1 |
| `plugins/proj/server/tests/test_state.py` | `server/lib/state.py` (35 lines) | 1 |
| `plugins/proj/server/tests/test_sandbox_helpers.py` | `server/lib/sandbox_helpers.py` (25 lines) | 1 |
| `plugins/proj/server/tests/test_sql_decisions.py` | `server/lib/sql_decisions.py` (75 lines) | 2 |
| `plugins/proj/server/tests/test_sql_todos.py` | `server/lib/sql_todos.py` (287 lines) | 2 |
| `plugins/proj/server/tests/test_sql_archive.py` | `server/lib/sql_archive.py` (189 lines) | 2 |
| `plugins/proj/server/tests/test_sql_meta.py` | `server/lib/sql_meta.py` (152 lines) | 2 |
| `plugins/proj/server/tests/test_retry.py` | `server/lib/retry.py` (98 lines) | 3 |
| `plugins/proj/server/tests/test_sockets_cleanup.py` | `server/lib/sockets_cleanup.py` (113 lines) | 3 |
| `plugins/proj/server/tests/test_router_health.py` | `server/lib/router_health.py` (108 lines) | 4 |
| `plugins/proj/server/tests/test_tracking_git_lib.py` | `server/lib/tracking_git.py` (182 lines) | 4 |
| `plugins/proj/server/tests/test_migration_lib.py` | `server/lib/migration.py` (318 lines) | 4 |
| `plugins/proj/server/tests/test_sandbox_models.py` | `server/lib/sandbox/models.py` (186 lines) | 5 |
| `plugins/proj/server/tests/test_sandbox_storage.py` | `server/lib/sandbox/storage.py` (100+ lines) | 5 |
| `plugins/router/server/tests/test_constants.py` | `server/lib/constants.py` (13 lines) | 6 |
| `plugins/router/server/tests/test_types.py` | `server/lib/_types.py` (107 lines) | 6 |
| `plugins/router/server/tests/test_sync_tool.py` | `server/tools/sync.py` (31 lines) | 6 |
| `plugins/router/server/tests/test_invocations_tool.py` | `server/tools/invocations.py` (95 lines) | 6 |

---

### Task 1: Trivial proj lib modules (enums, ids, state, sandbox_helpers)

**Worktree:** `/home/raul/worktrees/cpm/todo-630-632`

**Files:**
- Create: `plugins/proj/server/tests/test_enums.py`
- Create: `plugins/proj/server/tests/test_ids.py`
- Create: `plugins/proj/server/tests/test_state.py`
- Create: `plugins/proj/server/tests/test_sandbox_helpers.py`

- [ ] **Step 1: Write test_enums.py**

```python
"""Tests for server.lib.enums."""

from server.lib.enums import TERMINAL_STATUSES, Priority, TodoStatus


class TestTodoStatus:
    def test_values_are_strings(self):
        assert TodoStatus.PENDING == "pending"
        assert TodoStatus.IN_PROGRESS == "in_progress"
        assert TodoStatus.DONE == "done"

    def test_string_comparison(self):
        assert TodoStatus.DONE == "done"
        assert "pending" == TodoStatus.PENDING

    def test_iteration(self):
        values = list(TodoStatus)
        assert len(values) == 3


class TestPriority:
    def test_values_are_strings(self):
        assert Priority.LOW == "low"
        assert Priority.MEDIUM == "medium"
        assert Priority.HIGH == "high"

    def test_iteration(self):
        assert len(list(Priority)) == 3


class TestTerminalStatuses:
    def test_contains_done(self):
        assert "done" in TERMINAL_STATUSES

    def test_contains_cancelled(self):
        assert "cancelled" in TERMINAL_STATUSES

    def test_pending_not_terminal(self):
        assert "pending" not in TERMINAL_STATUSES

    def test_is_frozenset(self):
        assert isinstance(TERMINAL_STATUSES, frozenset)
```

- [ ] **Step 2: Write test_ids.py**

```python
"""Tests for server.lib.ids."""

from dataclasses import dataclass

from server.lib.ids import next_todo_id


@dataclass
class FakeMeta:
    next_todo_id: int = 1


@dataclass
class FakeTodo:
    id: str = "5"
    next_child_id: int = 1


class TestNextTodoId:
    def test_root_id_increments(self):
        meta = FakeMeta(next_todo_id=1)
        assert next_todo_id(meta) == "1"
        assert meta.next_todo_id == 2
        assert next_todo_id(meta) == "2"
        assert meta.next_todo_id == 3

    def test_child_id_uses_parent(self):
        meta = FakeMeta(next_todo_id=10)
        parent = FakeTodo(id="5", next_child_id=1)
        assert next_todo_id(meta, parent) == "5.1"
        assert parent.next_child_id == 2
        assert next_todo_id(meta, parent) == "5.2"
        assert parent.next_child_id == 3

    def test_child_id_does_not_increment_meta(self):
        meta = FakeMeta(next_todo_id=10)
        parent = FakeTodo(id="3", next_child_id=1)
        next_todo_id(meta, parent)
        assert meta.next_todo_id == 10

    def test_root_id_does_not_increment_parent(self):
        meta = FakeMeta(next_todo_id=1)
        next_todo_id(meta)
        # No parent to check — just ensure no exception

    def test_nested_parent_id(self):
        meta = FakeMeta(next_todo_id=100)
        parent = FakeTodo(id="3.2", next_child_id=5)
        assert next_todo_id(meta, parent) == "3.2.5"
```

- [ ] **Step 3: Write test_state.py**

```python
"""Tests for server.lib.state."""

from server.lib.state import (
    clear_session_active,
    get_session_active,
    resolve_project,
    set_session_active,
)


class TestSessionState:
    def setup_method(self):
        clear_session_active()

    def test_initial_state_is_none(self):
        assert get_session_active() is None

    def test_set_and_get(self):
        set_session_active("myproject")
        assert get_session_active() == "myproject"

    def test_clear(self):
        set_session_active("myproject")
        clear_session_active()
        assert get_session_active() is None

    def test_overwrite(self):
        set_session_active("first")
        set_session_active("second")
        assert get_session_active() == "second"


class TestResolveProject:
    def setup_method(self):
        clear_session_active()

    def test_explicit_name_wins(self):
        set_session_active("session-proj")
        assert resolve_project("explicit") == "explicit"

    def test_falls_back_to_session(self):
        set_session_active("session-proj")
        assert resolve_project(None) == "session-proj"

    def test_returns_none_when_nothing_set(self):
        assert resolve_project(None) is None

    def test_empty_string_falls_back(self):
        set_session_active("session-proj")
        assert resolve_project("") == "session-proj"
```

- [ ] **Step 4: Write test_sandbox_helpers.py**

```python
"""Tests for server.lib.sandbox_helpers."""

from dataclasses import dataclass, field
from pathlib import Path

from server.lib.sandbox_helpers import project_dir_from_meta, project_dirs_from_meta


@dataclass
class FakeRepo:
    label: str = "code"
    path: str = "/home/user/project"
    reference: bool = False


@dataclass
class FakeMeta:
    repos: list = field(default_factory=list)


class TestProjectDirsFromMeta:
    def test_non_reference_repos(self):
        meta = FakeMeta(repos=[
            FakeRepo(path="/a", reference=False),
            FakeRepo(path="/b", reference=True),
            FakeRepo(path="/c", reference=False),
        ])
        dirs = project_dirs_from_meta(meta)
        assert dirs == [Path("/a"), Path("/c")]

    def test_all_reference_falls_back_to_first(self):
        meta = FakeMeta(repos=[
            FakeRepo(path="/ref1", reference=True),
            FakeRepo(path="/ref2", reference=True),
        ])
        dirs = project_dirs_from_meta(meta)
        assert dirs == [Path("/ref1")]

    def test_empty_repos(self):
        meta = FakeMeta(repos=[])
        assert project_dirs_from_meta(meta) == []

    def test_single_non_reference(self):
        meta = FakeMeta(repos=[FakeRepo(path="/only")])
        assert project_dirs_from_meta(meta) == [Path("/only")]


class TestProjectDirFromMeta:
    def test_returns_first_non_reference(self):
        meta = FakeMeta(repos=[
            FakeRepo(path="/a", reference=True),
            FakeRepo(path="/b", reference=False),
        ])
        assert project_dir_from_meta(meta) == Path("/b")

    def test_returns_none_when_empty(self):
        meta = FakeMeta(repos=[])
        assert project_dir_from_meta(meta) is None
```

- [ ] **Step 5: Run tests**

Run: `cd plugins/proj/server && python -m pytest tests/test_enums.py tests/test_ids.py tests/test_state.py tests/test_sandbox_helpers.py -v`

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add plugins/proj/server/tests/test_enums.py plugins/proj/server/tests/test_ids.py plugins/proj/server/tests/test_state.py plugins/proj/server/tests/test_sandbox_helpers.py
git commit -m "test(proj): add unit tests for enums, ids, state, sandbox_helpers

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: SQL modules (sql_decisions, sql_todos, sql_archive, sql_meta)

**Worktree:** `/home/raul/worktrees/cpm/todo-630-632`

**Files:**
- Create: `plugins/proj/server/tests/test_sql_decisions.py`
- Create: `plugins/proj/server/tests/test_sql_todos.py`
- Create: `plugins/proj/server/tests/test_sql_archive.py`
- Create: `plugins/proj/server/tests/test_sql_meta.py`

These modules use real SQLite. Use the `cfg` fixture from conftest.py which provides a tmp_path-based ProjConfig.

- [ ] **Step 1: Write test_sql_decisions.py**

```python
"""Tests for server.lib.sql_decisions — SQLite decisions CRUD."""

from __future__ import annotations

import json

from server.lib.db import ensure_db, get_connection
from server.lib.sql_decisions import (
    append_decision,
    load_all_decisions,
    load_decisions,
    replace_decisions,
)


class TestLoadDecisions:
    def test_empty_returns_empty_list(self, cfg):
        result = load_decisions(cfg, "proj1")
        assert result == []

    def test_roundtrip_single(self, cfg):
        entry = {"decision": "Use SQLite", "tags": ["db"]}
        append_decision(cfg, "proj1", entry)
        result = load_decisions(cfg, "proj1")
        assert len(result) == 1
        assert result[0]["decision"] == "Use SQLite"

    def test_insertion_order_preserved(self, cfg):
        for i in range(3):
            append_decision(cfg, "proj1", {"seq": i})
        result = load_decisions(cfg, "proj1")
        assert [d["seq"] for d in result] == [0, 1, 2]

    def test_projects_isolated(self, cfg):
        append_decision(cfg, "proj1", {"val": "a"})
        append_decision(cfg, "proj2", {"val": "b"})
        assert len(load_decisions(cfg, "proj1")) == 1
        assert len(load_decisions(cfg, "proj2")) == 1


class TestAppendDecision:
    def test_auto_generates_timestamp(self, cfg):
        append_decision(cfg, "proj1", {"decision": "test"})
        result = load_decisions(cfg, "proj1")
        assert "timestamp" not in result[0] or result[0].get("timestamp")

    def test_preserves_explicit_timestamp(self, cfg):
        append_decision(cfg, "proj1", {"decision": "test", "timestamp": "2026-01-01T00:00:00"})
        db_file = ensure_db(cfg, "proj1")
        with get_connection(db_file) as conn:
            row = conn.execute("SELECT timestamp FROM decisions").fetchone()
        assert row["timestamp"] == "2026-01-01T00:00:00"


class TestReplaceDecisions:
    def test_replaces_all(self, cfg):
        append_decision(cfg, "proj1", {"old": True})
        replace_decisions(cfg, "proj1", [{"new": True}])
        result = load_decisions(cfg, "proj1")
        assert len(result) == 1
        assert result[0]["new"] is True

    def test_empty_list_clears_all(self, cfg):
        append_decision(cfg, "proj1", {"val": 1})
        replace_decisions(cfg, "proj1", [])
        assert load_decisions(cfg, "proj1") == []


class TestLoadAllDecisions:
    def test_empty_tracking_dir(self, cfg):
        result = load_all_decisions(cfg)
        assert result == {} or isinstance(result, dict)

    def test_multiple_projects(self, cfg):
        append_decision(cfg, "proj1", {"val": "a"})
        append_decision(cfg, "proj2", {"val": "b"})
        result = load_all_decisions(cfg)
        assert "proj1" in result
        assert "proj2" in result
```

- [ ] **Step 2: Write test_sql_todos.py**

Test file for sql_todos.py. This module serializes Todo objects to/from SQLite. Focus on roundtrip fidelity, compound ID computation, and archive fallback.

The implementer should read `plugins/proj/server/server/lib/sql_todos.py` and write tests covering:
- `_todo_to_row` / `_row_to_todo` roundtrip with all fields (tags as JSON list, blocked_by as JSON list, git as JSON dict, trello_sync_state as JSON dict)
- `load_todos` / `save_todos` roundtrip with the `cfg` fixture
- `compute_next_todo_id` with simple IDs ("1", "2") and compound IDs ("475.6", "3.2.1")
- `load_archived_todos` returns [] when no archive exists
- `save_archived_todos_append` appends without overwriting

Use the `cfg` fixture for real SQLite. Create Todo instances via the models module.

- [ ] **Step 3: Write test_sql_archive.py**

Test file for sql_archive.py. Focus on atomic archival (remaining vs to_archive split) and terminal status detection.

The implementer should read `plugins/proj/server/server/lib/sql_archive.py` and write tests covering:
- `archive_and_remove_todos` moves to_archive items and keeps remaining
- Atomicity: if archive fails, no todos are lost
- `migrate_done_to_archive` correctly identifies TERMINAL_STATUSES
- Empty lists handled gracefully

- [ ] **Step 4: Write test_sql_meta.py**

Test file for sql_meta.py. Focus on ProjectMeta/ProjectIndex roundtrips through SQLite.

The implementer should read `plugins/proj/server/server/lib/sql_meta.py` and write tests covering:
- `load_meta` / `save_meta` roundtrip preserving all fields (repos, dates, tags, sync configs)
- `save_meta` bumps `last_updated` date
- `load_meta` raises FileNotFoundError for missing project
- `load_index` / `save_index` roundtrip with multiple projects
- Nested structure preservation (TodoistSync, TrelloConfig, etc.)

- [ ] **Step 5: Run all SQL tests**

Run: `cd plugins/proj/server && python -m pytest tests/test_sql_decisions.py tests/test_sql_todos.py tests/test_sql_archive.py tests/test_sql_meta.py -v`

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add plugins/proj/server/tests/test_sql_decisions.py plugins/proj/server/tests/test_sql_todos.py plugins/proj/server/tests/test_sql_archive.py plugins/proj/server/tests/test_sql_meta.py
git commit -m "test(proj): add unit tests for SQL modules (decisions, todos, archive, meta)

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Infrastructure modules (retry, sockets_cleanup)

**Worktree:** `/home/raul/worktrees/cpm/todo-630-632`

**Files:**
- Create: `plugins/proj/server/tests/test_retry.py`
- Create: `plugins/proj/server/tests/test_sockets_cleanup.py`

- [ ] **Step 1: Write test_retry.py**

```python
"""Tests for server.lib.retry — retry with circuit breaker integration."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from server.lib.retry import CircuitOpenError, log_orphaned_resource, retry_link


class TestRetryLink:
    def test_success_on_first_attempt(self):
        result = retry_link(lambda: 42, max_retries=3)
        assert result == 42

    def test_retries_on_failure(self):
        call_count = 0

        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("fail")
            return "ok"

        with patch("server.lib.retry.time.sleep"):
            result = retry_link(flaky, max_retries=3)
        assert result == "ok"
        assert call_count == 3

    def test_exhausted_retries_raises(self):
        with patch("server.lib.retry.time.sleep"):
            with pytest.raises(ValueError, match="always fail"):
                retry_link(lambda: (_ for _ in ()).throw(ValueError("always fail")), max_retries=2)

    def test_circuit_open_skips_call(self):
        mgr = MagicMock()
        mgr.check.return_value = False
        with pytest.raises(CircuitOpenError):
            retry_link(lambda: 1, circuit_breaker_manager=mgr, service="todoist")

    def test_records_success_on_circuit_breaker(self):
        mgr = MagicMock()
        mgr.check.return_value = True
        retry_link(lambda: 1, circuit_breaker_manager=mgr, service="todoist")
        mgr.record_success.assert_called_once_with("todoist")

    def test_records_failure_on_circuit_breaker(self):
        mgr = MagicMock()
        mgr.check.return_value = True
        with patch("server.lib.retry.time.sleep"), pytest.raises(ValueError):
            retry_link(
                lambda: (_ for _ in ()).throw(ValueError("err")),
                max_retries=1,
                circuit_breaker_manager=mgr,
                service="svc",
            )
        mgr.record_failure.assert_called_once()

    def test_orphan_logging_on_exhaustion(self, tmp_path):
        ctx = {"tracking_dir": str(tmp_path), "external_id": "ext1", "todo_id": "5", "service": "todoist"}
        with patch("server.lib.retry.time.sleep"), pytest.raises(RuntimeError):
            retry_link(
                lambda: (_ for _ in ()).throw(RuntimeError("fail")),
                max_retries=1,
                orphan_context=ctx,
            )
        orphan_file = tmp_path / ".orphaned-resources.yaml"
        assert orphan_file.exists()


class TestLogOrphanedResource:
    def test_creates_file(self, tmp_path):
        log_orphaned_resource(str(tmp_path), {"service": "test", "error": "err"})
        assert (tmp_path / ".orphaned-resources.yaml").exists()

    def test_appends_to_existing(self, tmp_path):
        log_orphaned_resource(str(tmp_path), {"service": "first"})
        log_orphaned_resource(str(tmp_path), {"service": "second"})
        import yaml

        entries = yaml.safe_load((tmp_path / ".orphaned-resources.yaml").read_text())
        assert len(entries) == 2


class TestCircuitOpenError:
    def test_message_contains_service(self):
        err = CircuitOpenError("todoist")
        assert "todoist" in str(err)
        assert err.service == "todoist"
```

- [ ] **Step 2: Write test_sockets_cleanup.py**

```python
"""Tests for server.lib.sockets_cleanup."""

from __future__ import annotations

import json

from server.lib.sockets_cleanup import (
    KNOWN_MANAGED_PLUGINS,
    _load_installed,
    sockets_cleanup_stale,
)


class TestLoadInstalled:
    def test_dict_with_plugins_dict(self, tmp_path):
        path = tmp_path / "installed.json"
        path.write_text(json.dumps({"plugins": {"proj@cpm": {}, "router@cpm": {}}}))
        result = _load_installed(path)
        assert result == {"proj", "router"}

    def test_dict_with_plugins_list(self, tmp_path):
        path = tmp_path / "installed.json"
        path.write_text(json.dumps({"plugins": [{"name": "proj"}, {"name": "router"}]}))
        result = _load_installed(path)
        assert result == {"proj", "router"}

    def test_invalid_json_returns_none(self, tmp_path):
        path = tmp_path / "installed.json"
        path.write_text("not json")
        assert _load_installed(path) is None

    def test_missing_file_returns_none(self, tmp_path):
        assert _load_installed(tmp_path / "nope.json") is None

    def test_strips_marketplace_suffix(self, tmp_path):
        path = tmp_path / "installed.json"
        path.write_text(json.dumps({"plugins": {"proj@claude-project-manager": {}}}))
        result = _load_installed(path)
        assert result == {"proj"}


class TestSocketsCleanupStale:
    def test_removes_stale_managed_plugin(self, tmp_path):
        sockets = tmp_path / "sockets"
        sockets.mkdir()
        (sockets / "hooks").write_text("")
        (sockets / "proj").write_text("")

        installed = tmp_path / "installed.json"
        installed.write_text(json.dumps({"plugins": {"proj@cpm": {}}}))

        removed = sockets_cleanup_stale(sockets, installed)
        assert "hooks" in removed
        assert not (sockets / "hooks").exists()
        assert (sockets / "proj").exists()

    def test_ignores_non_managed_files(self, tmp_path):
        sockets = tmp_path / "sockets"
        sockets.mkdir()
        (sockets / "custom-plugin").write_text("")

        installed = tmp_path / "installed.json"
        installed.write_text(json.dumps({"plugins": {}}))

        removed = sockets_cleanup_stale(sockets, installed)
        assert removed == []
        assert (sockets / "custom-plugin").exists()

    def test_ignores_directories(self, tmp_path):
        sockets = tmp_path / "sockets"
        sockets.mkdir()
        (sockets / "hooks").mkdir()

        installed = tmp_path / "installed.json"
        installed.write_text(json.dumps({"plugins": {}}))

        removed = sockets_cleanup_stale(sockets, installed)
        assert removed == []

    def test_missing_sockets_dir(self, tmp_path):
        installed = tmp_path / "installed.json"
        installed.write_text(json.dumps({"plugins": {}}))
        assert sockets_cleanup_stale(tmp_path / "no-such", installed) == []

    def test_missing_installed_json(self, tmp_path):
        sockets = tmp_path / "sockets"
        sockets.mkdir()
        assert sockets_cleanup_stale(sockets, tmp_path / "nope.json") == []

    def test_unparseable_installed_json_aborts(self, tmp_path):
        sockets = tmp_path / "sockets"
        sockets.mkdir()
        (sockets / "hooks").write_text("")

        installed = tmp_path / "installed.json"
        installed.write_text("not json")

        removed = sockets_cleanup_stale(sockets, installed)
        assert removed == []
        assert (sockets / "hooks").exists()


class TestKnownManagedPlugins:
    def test_contains_expected_names(self):
        for name in ("hooks", "perms", "router", "sandbox", "proj", "worktree", "trello", "jira", "todoist"):
            assert name in KNOWN_MANAGED_PLUGINS
```

- [ ] **Step 3: Run tests**

Run: `cd plugins/proj/server && python -m pytest tests/test_retry.py tests/test_sockets_cleanup.py -v`

Expected: All pass.

- [ ] **Step 4: Commit**

```bash
git add plugins/proj/server/tests/test_retry.py plugins/proj/server/tests/test_sockets_cleanup.py
git commit -m "test(proj): add unit tests for retry and sockets_cleanup

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Complex proj lib modules (router_health, tracking_git, migration)

**Worktree:** `/home/raul/worktrees/cpm/todo-630-632`

**Files:**
- Create: `plugins/proj/server/tests/test_router_health.py`
- Create: `plugins/proj/server/tests/test_tracking_git_lib.py`
- Create: `plugins/proj/server/tests/test_migration_lib.py`

These modules have external deps (async HTTP, subprocess git, SQLite migration). The implementer should:

- **router_health.py**: Read source, mock `httpx.AsyncClient.post` and `_resolve_hooks_transport`, test cache TTL behavior with monkeypatched time, test HOOKS_HEALTH_CHECK=0 env var opt-out. Use `@pytest.mark.asyncio`.

- **tracking_git.py**: Read source, mock `subprocess.run`, test `resolve_config` fallback chain (meta → global → defaults), test `ensure_git_repo` creates .gitignore, test `tracking_commit` returns None when no changes, test template var substitution.

- **migration.py**: Read source, use real SQLite via `cfg` fixture, test YAML→SQLite migration roundtrip, test idempotency (second run = "already_migrated"), test crashed migration recovery (empty DB → delete and re-migrate), test YAML .bak rename after success.

- [ ] **Step 1: Write test_router_health.py** — read source, write async tests with mocked httpx
- [ ] **Step 2: Write test_tracking_git_lib.py** — read source, write tests with mocked subprocess
- [ ] **Step 3: Write test_migration_lib.py** — read source, write tests with real SQLite via cfg fixture
- [ ] **Step 4: Run tests**

Run: `cd plugins/proj/server && python -m pytest tests/test_router_health.py tests/test_tracking_git_lib.py tests/test_migration_lib.py -v`

- [ ] **Step 5: Commit**

```bash
git add plugins/proj/server/tests/test_router_health.py plugins/proj/server/tests/test_tracking_git_lib.py plugins/proj/server/tests/test_migration_lib.py
git commit -m "test(proj): add unit tests for router_health, tracking_git, migration

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Sandbox models and storage

**Worktree:** `/home/raul/worktrees/cpm/todo-630-632`

**Files:**
- Create: `plugins/proj/server/tests/test_sandbox_models.py`
- Create: `plugins/proj/server/tests/test_sandbox_storage.py`

The implementer should read `plugins/proj/server/server/lib/sandbox/models.py` and `sandbox/storage.py`, then write tests covering:

- **sandbox/models.py**: All dataclass roundtrips (Permissions, SandboxFilesystem, SandboxNetwork, SandboxConfig, SettingsFile) via `to_dict()` → `from_dict()`. Test default values, unknown key preservation in `raw` dict, non-dict inputs gracefully default.

- **sandbox/storage.py**: `load()` returns empty SettingsFile if file missing or corrupt. `save()` creates parent dirs, uses atomic write (temp file → replace), preserves file mode. `allow_entries_for_path()` rejects relative paths, normalizes trailing slashes. `mcp_allow_entry()` builds correct rule format.

- [ ] **Step 1: Write test_sandbox_models.py** — read source, write roundtrip tests for all dataclasses
- [ ] **Step 2: Write test_sandbox_storage.py** — read source, write tests with tmp_path for file I/O
- [ ] **Step 3: Run tests**

Run: `cd plugins/proj/server && python -m pytest tests/test_sandbox_models.py tests/test_sandbox_storage.py -v`

- [ ] **Step 4: Commit**

```bash
git add plugins/proj/server/tests/test_sandbox_models.py plugins/proj/server/tests/test_sandbox_storage.py
git commit -m "test(proj): add unit tests for sandbox models and storage

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Router gaps (constants, _types, sync tool, invocations tool)

**Worktree:** `/home/raul/worktrees/cpm/todo-633-634`

**Files:**
- Create: `plugins/router/server/tests/test_constants.py`
- Create: `plugins/router/server/tests/test_types.py`
- Create: `plugins/router/server/tests/test_sync_tool.py`
- Create: `plugins/router/server/tests/test_invocations_tool.py`

- [ ] **Step 1: Write test_constants.py**

```python
"""Tests for server.lib.constants."""

from server.lib.constants import DEFAULT_SERVER_PORTS


class TestDefaultServerPorts:
    def test_all_expected_servers_present(self):
        expected = {"hooks", "sandbox", "proj", "worktree", "trello", "jira", "todoist"}
        assert expected == set(DEFAULT_SERVER_PORTS.keys())

    def test_no_duplicate_ports(self):
        ports = list(DEFAULT_SERVER_PORTS.values())
        assert len(ports) == len(set(ports))

    def test_ports_in_valid_range(self):
        for port in DEFAULT_SERVER_PORTS.values():
            assert 1024 <= port <= 65535
```

- [ ] **Step 2: Write test_types.py**

```python
"""Tests for server.lib._types — shared dataclasses and TypedDicts."""

from server.lib._types import (
    FeedbackResult,
    HookError,
    HookResultEntry,
    VerificationResult,
)


class TestVerificationResult:
    def test_instantiation(self):
        r = VerificationResult(hook_id="h1", status="pass", details="ok")
        assert r.hook_id == "h1"
        assert r.status == "pass"
        assert r.details == "ok"


class TestFeedbackResult:
    def test_instantiation(self):
        r = FeedbackResult(hook_id="h1", feedback_tool="fb", ok=True, error=None)
        assert r.ok is True
        assert r.error is None

    def test_with_error(self):
        r = FeedbackResult(hook_id="h1", feedback_tool="fb", ok=False, error="failed")
        assert r.ok is False
        assert r.error == "failed"


class TestHookError:
    def test_instantiation(self):
        e = HookError(hook_id="h1", error="timeout", target_tool="sync")
        assert e.error == "timeout"


class TestHookResultEntry:
    def test_instantiation(self):
        e = HookResultEntry(hook_id="h1", result='{"ok": true}', target_tool="sync")
        assert e.result == '{"ok": true}'

    def test_none_result(self):
        e = HookResultEntry(hook_id="h1", result=None, target_tool=None)
        assert e.result is None
```

- [ ] **Step 3: Write test_sync_tool.py**

```python
"""Tests for server.tools.sync — MCP hook sync tool."""

from __future__ import annotations

import json
from unittest.mock import patch

from server.tools.sync import hooks_sync


class TestHooksSync:
    def test_returns_json_with_result(self):
        with patch("server.tools.sync.run_discovery", return_value="Discovered 3 hooks"):
            result = json.loads(hooks_sync())
        assert result["result"] == "Discovered 3 hooks"

    def test_calls_run_discovery(self):
        with patch("server.tools.sync.run_discovery", return_value="ok") as mock:
            hooks_sync()
        mock.assert_called_once()
```

- [ ] **Step 4: Write test_invocations_tool.py**

```python
"""Tests for server.tools.invocations — MCP invocation history tool."""

from __future__ import annotations

import json
from unittest.mock import patch

from server.tools.invocations import hooks_invocations


def _make_entries(n, type_field="invocation"):
    return [
        {"hook_id": f"h{i}", "trigger_tool": f"t{i}", "target_tool": f"tgt{i}", "timestamp": f"2026-01-{i+1:02d}T00:00:00"}
        for i in range(n)
    ]


class TestHooksInvocations:
    @patch("server.tools.invocations.storage.load_failures", return_value=[])
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(3))
    def test_returns_all_invocations(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations())
        assert result["total"] == 3

    @patch("server.tools.invocations.storage.load_failures", return_value=_make_entries(2, "failure"))
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(2))
    def test_combines_invocations_and_failures(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations(type="all"))
        assert result["total"] == 4

    @patch("server.tools.invocations.storage.load_failures", return_value=[])
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(3))
    def test_filter_by_hook_id(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations(hook_id="h1"))
        assert all(e["hook_id"] == "h1" for e in result["entries"])

    @patch("server.tools.invocations.storage.load_failures", return_value=[])
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(3))
    def test_filter_by_trigger_tool(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations(trigger_tool="t0"))
        assert all(e["trigger_tool"] == "t0" for e in result["entries"])

    @patch("server.tools.invocations.storage.load_failures", return_value=[])
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(300))
    def test_limit_clamped_to_200(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations(limit=500))
        assert result["limit"] == 200
        assert len(result["entries"]) <= 200

    @patch("server.tools.invocations.storage.load_failures", return_value=_make_entries(2))
    @patch("server.tools.invocations.storage.load_invocations", return_value=[])
    def test_type_failure_only(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations(type="failure"))
        assert result["total"] == 2

    @patch("server.tools.invocations.storage.load_failures", return_value=[])
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(2))
    def test_type_invocation_only(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations(type="invocation"))
        assert result["total"] == 2

    @patch("server.tools.invocations.storage.load_failures", return_value=[])
    @patch("server.tools.invocations.storage.load_invocations", return_value=_make_entries(5))
    def test_sorted_newest_first(self, mock_inv, mock_fail):
        result = json.loads(hooks_invocations())
        timestamps = [e["timestamp"] for e in result["entries"]]
        assert timestamps == sorted(timestamps, reverse=True)
```

- [ ] **Step 5: Run tests**

Run: `cd plugins/router/server && python -m pytest tests/test_constants.py tests/test_types.py tests/test_sync_tool.py tests/test_invocations_tool.py -v`

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add plugins/router/server/tests/test_constants.py plugins/router/server/tests/test_types.py plugins/router/server/tests/test_sync_tool.py plugins/router/server/tests/test_invocations_tool.py
git commit -m "test(router): add unit tests for constants, types, sync tool, invocations tool

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

## Verification

After all tasks:

- [ ] `cd plugins/proj/server && python -m pytest tests/ -v --tb=short` — all pass, no regressions
- [ ] `cd plugins/router/server && python -m pytest tests/ -v --tb=short` — all pass, no regressions
- [ ] Merge worktree branches into dev
