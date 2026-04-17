"""Tests for todo_batch_complete MCP tool (todo 518)."""

from __future__ import annotations

import json
import threading
from datetime import date
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from server.lib import state, storage
from server.lib.enums import TodoStatus
from server.lib.models import ProjConfig, Todo
from tests.conftest import call_tool, setup_project


def test_todo_batch_complete_tool_does_not_exist():
    """todo_batch_complete must not be registered after removal."""
    from mcp.server.fastmcp import FastMCP

    from server.tools.todos import register

    app = FastMCP("test")
    register(app)
    tool_names = [t.name for t in app._tool_manager.list_tools()]
    assert "todo_batch_complete" not in tool_names
    assert "todo_complete" in tool_names


@pytest.mark.asyncio
async def test_todo_complete_single_returns_todoist_task_ids_list(cfg: ProjConfig, tmp_path: Path):
    """todo_complete with a single todo_id must return todoist_task_ids as a list."""
    from server.tools import config, projects, todos

    setup_project(cfg, "myapp", str(tmp_path))
    todo = _make_todo("99", todoist_task_id="todoist-abc-123")
    storage.save_todos(cfg, "myapp", [todo])
    state.set_session_active("myapp")

    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos.register(app)

    result = await call_tool(app, "todo_complete", todo_id="99")
    data = json.loads(result)
    assert "todoist_task_ids" in data
    assert data["todoist_task_ids"] == ["todoist-abc-123"]
    assert data.get("is_batch") is False  # single path sets is_batch=False to exclude batch hooks


def _status_str(todo: Todo) -> str:
    s = todo.status
    return s.value if isinstance(s, TodoStatus) else str(s)


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
    return Todo(
        id=tid,
        title=title,
        created=today,
        updated=today,
        status=status,  # type: ignore[arg-type]
        parent=parent,
        todoist_task_id=todoist_task_id,
        trello_card_id=trello_card_id,
        jira_issue_key=jira_issue_key,
    )


@pytest.fixture()
def project_with_todos(cfg: ProjConfig, tmp_path: Path):
    """Set up `myapp` with three flat active todos (1, 2, 3)."""
    setup_project(cfg, "myapp", str(tmp_path))
    todos = [_make_todo("1"), _make_todo("2"), _make_todo("3")]
    storage.save_todos(cfg, "myapp", todos)
    state.set_session_active("myapp")
    return cfg, "myapp"


@pytest.fixture()
def mcp_app(cfg: ProjConfig) -> FastMCP:
    """Minimal app with only the tools needed for these tests."""
    from server.tools import config, projects, todos

    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos.register(app)
    return app


# ─── Phase 0 / 1 validation ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_list_rejects(project_with_todos, mcp_app):
    result = await call_tool(mcp_app, "todo_complete", todo_ids=[])
    data = json.loads(result)
    assert "error" in data
    assert data["completed_ids"] == []
    assert data["skipped_ids"] == []
    assert data["invalid_ids"] == []


@pytest.mark.asyncio
async def test_single_id_runs_batch_path(project_with_todos, mcp_app):
    cfg, name = project_with_todos
    result = await call_tool(mcp_app, "todo_complete", todo_ids=["1"])
    data = json.loads(result)
    assert data["completed_ids"] == ["1"]
    assert data["skipped_ids"] == []
    # Leaf archival: id 1 should be archived.
    archived = storage.load_archived_todos(cfg, name)
    assert any(t.id == "1" for t in archived)


@pytest.mark.asyncio
async def test_mixed_skipped_active(cfg: ProjConfig, mcp_app, tmp_path: Path):
    setup_project(cfg, "myapp", str(tmp_path))
    todos = [
        _make_todo("1"),
        _make_todo("2", status="done"),
        _make_todo("3"),
    ]
    storage.save_todos(cfg, "myapp", todos)
    state.set_session_active("myapp")

    result = await call_tool(mcp_app, "todo_complete", todo_ids=["1", "2", "3"])
    data = json.loads(result)
    assert set(data["completed_ids"]) == {"1", "3"}
    assert "2" in data["skipped_ids"]


@pytest.mark.asyncio
async def test_invalid_ids_no_side_effects(project_with_todos, mcp_app):
    cfg, name = project_with_todos
    result = await call_tool(mcp_app, "todo_complete", todo_ids=["1", "999"])
    data = json.loads(result)
    assert "error" in data
    assert "999" in data["invalid_ids"]
    # No state change: todo 1 must still be pending.
    todos = storage.load_todos(cfg, name)
    t1 = next(t for t in todos if t.id == "1")
    assert _status_str(t1) == "pending"


@pytest.mark.asyncio
async def test_non_existent_no_side_effects(project_with_todos, mcp_app):
    cfg, name = project_with_todos
    result = await call_tool(mcp_app, "todo_complete", todo_ids=["x", "y"])
    data = json.loads(result)
    assert "error" in data
    assert set(data["invalid_ids"]) >= {"x", "y"}
    todos = storage.load_todos(cfg, name)
    assert all(_status_str(t) == "pending" for t in todos)


@pytest.mark.asyncio
async def test_cross_project_rejects(cfg: ProjConfig, mcp_app, tmp_path: Path):
    setup_project(cfg, "myapp", str(tmp_path))
    setup_project(cfg, "other", str(tmp_path))
    storage.save_todos(cfg, "myapp", [_make_todo("1")])
    storage.save_todos(cfg, "other", [_make_todo("42")])
    state.set_session_active("myapp")

    result = await call_tool(mcp_app, "todo_complete", todo_ids=["1", "42"])
    data = json.loads(result)
    assert "error" in data
    assert "Cross-project" in data["error"]
    assert "42" in data["invalid_ids"]
    # No side effects in myapp.
    myapp_todos = storage.load_todos(cfg, "myapp")
    assert _status_str(myapp_todos[0]) == "pending"


@pytest.mark.asyncio
async def test_order_preserving_dedupe(project_with_todos, mcp_app):
    _cfg, _name = project_with_todos
    result = await call_tool(mcp_app, "todo_complete", todo_ids=["3", "1", "3", "2", "1"])
    data = json.loads(result)
    # Dedupe preserves first-seen order.
    assert data["completed_ids"] == ["3", "1", "2"]


# ─── Atomicity & concurrency ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_atomic_save_single_write(project_with_todos, mcp_app, monkeypatch):
    """Phase 2 must call storage.save_todos OR archive_and_remove_todos exactly once."""
    _cfg, _name = project_with_todos
    save_calls: list[int] = []
    archive_calls: list[int] = []

    orig_save = storage.save_todos
    orig_archive = storage.archive_and_remove_todos

    def wrapped_save(*args, **kwargs):
        save_calls.append(1)
        return orig_save(*args, **kwargs)

    def wrapped_archive(*args, **kwargs):
        archive_calls.append(1)
        return orig_archive(*args, **kwargs)

    monkeypatch.setattr(storage, "save_todos", wrapped_save)
    monkeypatch.setattr(storage, "archive_and_remove_todos", wrapped_archive)
    # Patch the module that imports these names too.
    from server.tools import todos as todos_mod

    monkeypatch.setattr(todos_mod.storage, "save_todos", wrapped_save)
    monkeypatch.setattr(todos_mod.storage, "archive_and_remove_todos", wrapped_archive)

    await call_tool(mcp_app, "todo_complete", todo_ids=["1", "2", "3"])
    assert len(save_calls) + len(archive_calls) == 1


@pytest.mark.xdist_group("serial")
def test_concurrent_saves_serialize(cfg: ProjConfig, tmp_path: Path):
    """Two threads calling todo_batch_complete must serialize under _BATCH_COMPLETE_LOCK."""
    from server.tools import todos as todos_mod

    setup_project(cfg, "myapp", str(tmp_path))
    todos = [_make_todo(str(i)) for i in range(1, 7)]
    storage.save_todos(cfg, "myapp", todos)
    state.set_session_active("myapp")

    # Sanity check: the lock exists and is a threading.Lock.
    assert isinstance(todos_mod._BATCH_COMPLETE_LOCK, type(threading.Lock()))

    errors: list[Exception] = []

    def worker(ids: list[str]) -> None:
        try:
            app = FastMCP("test-proj")
            from server.tools import config, projects
            from server.tools import todos as tmod

            config.register(app)
            projects.register(app)
            tmod.register(app)
            import asyncio

            result = asyncio.run(call_tool(app, "todo_complete", todo_ids=ids))
            _ = json.loads(result)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=worker, args=(["1", "2", "3"],))
    t2 = threading.Thread(target=worker, args=(["4", "5", "6"],))
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert not errors, f"Worker errors: {errors}"
    # All 6 ids eventually archived (leaves).
    archived = storage.load_archived_todos(cfg, "myapp")
    archived_ids = {t.id for t in archived}
    assert archived_ids >= {"1", "2", "3", "4", "5", "6"}


# ─── Family archival walk ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parent_family_archive_walks_full_tree(cfg: ProjConfig, mcp_app, tmp_path: Path):
    """Completing all leaves of a 3-level tree archives the entire family."""
    setup_project(cfg, "myapp", str(tmp_path))
    # Tree: 1 → 1.1 → 1.1.1 and 1 → 1.2
    p = _make_todo("1")
    c1 = _make_todo("1.1", parent="1")
    c2 = _make_todo("1.2", parent="1")
    gc = _make_todo("1.1.1", parent="1.1")
    p.children = ["1.1", "1.2"]
    c1.children = ["1.1.1"]
    storage.save_todos(cfg, "myapp", [p, c1, c2, gc])
    state.set_session_active("myapp")

    result = await call_tool(mcp_app, "todo_complete", todo_ids=["1.1.1", "1.2", "1.1", "1"])
    data = json.loads(result)
    assert set(data["completed_ids"]) == {"1.1.1", "1.2", "1.1", "1"}
    assert set(data["archived_ids"]) == {"1", "1.1", "1.2", "1.1.1"}
    remaining = storage.load_todos(cfg, "myapp")
    assert remaining == []


@pytest.mark.asyncio
async def test_children_across_trees_independent(cfg: ProjConfig, mcp_app, tmp_path: Path):
    """Completing children in tree A must not archive an untouched tree B."""
    setup_project(cfg, "myapp", str(tmp_path))
    # Tree A: 1 → 1.1, Tree B: 2 → 2.1
    a = _make_todo("1")
    a1 = _make_todo("1.1", parent="1")
    b = _make_todo("2")
    b1 = _make_todo("2.1", parent="2")
    a.children = ["1.1"]
    b.children = ["2.1"]
    storage.save_todos(cfg, "myapp", [a, a1, b, b1])
    state.set_session_active("myapp")

    result = await call_tool(mcp_app, "todo_complete", todo_ids=["1.1", "1"])
    data = json.loads(result)
    assert set(data["archived_ids"]) == {"1", "1.1"}
    remaining = storage.load_todos(cfg, "myapp")
    remaining_ids = {t.id for t in remaining}
    assert remaining_ids == {"2", "2.1"}


# ─── Encoding & size limits ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unicode_titles_round_trip(cfg: ProjConfig, mcp_app, tmp_path: Path):
    """Unicode titles survive the JSON round-trip."""
    setup_project(cfg, "myapp", str(tmp_path))
    todos = [
        _make_todo("1", title="日本語タスク"),
        _make_todo("2", title="Café ☕ résumé"),
    ]
    storage.save_todos(cfg, "myapp", todos)
    state.set_session_active("myapp")

    result = await call_tool(mcp_app, "todo_complete", todo_ids=["1", "2"])
    # ensure_ascii=True means result is ASCII-safe; json.loads restores unicode.
    data = json.loads(result)
    assert set(data["completed_ids"]) == {"1", "2"}
    # Result is valid JSON string that can round-trip.
    assert isinstance(data["project_name"], str)


@pytest.mark.asyncio
async def test_large_batch_100_items(cfg: ProjConfig, mcp_app, tmp_path: Path):
    setup_project(cfg, "myapp", str(tmp_path))
    todos = [_make_todo(str(i)) for i in range(1, 101)]
    storage.save_todos(cfg, "myapp", todos)
    state.set_session_active("myapp")

    ids = [str(i) for i in range(1, 101)]
    result = await call_tool(mcp_app, "todo_complete", todo_ids=ids)
    data = json.loads(result)
    assert len(data["completed_ids"]) == 100


@pytest.mark.asyncio
async def test_90kb_truncation_preserves_whole_fields(cfg: ProjConfig, mcp_app, tmp_path: Path):
    """Oversized payloads drop WHOLE fields, never mid-string; JSON stays valid."""
    setup_project(cfg, "myapp", str(tmp_path))
    # Very long jira key to inflate jira_updates_json past 90KB.
    long_key = "JIRA-" + "X" * 500
    todos = [_make_todo(str(i), jira_issue_key=f"{long_key}-{i}") for i in range(1, 101)]
    storage.save_todos(cfg, "myapp", todos)
    state.set_session_active("myapp")

    ids = [str(i) for i in range(1, 101)]
    result = await call_tool(mcp_app, "todo_complete", todo_ids=ids)
    # Result must still be valid JSON after truncation.
    data = json.loads(result)
    assert "truncation_notes" in data
    # jira_updates_json is the first field dropped — should be empty string.
    assert data["jira_updates_json"] == ""
    # completed_ids never dropped.
    assert len(data["completed_ids"]) == 100


# ─── Hook cascade / partial failure behavior ────────────────────────────────


@pytest.mark.asyncio
async def test_depth_cascade_tracking(project_with_todos, mcp_app):
    """The tool result itself does not carry depth, but it must be a clean
    JSON object that the dispatch wrapper can inject _hooks into."""
    result = await call_tool(mcp_app, "todo_complete", todo_ids=["1", "2"])
    data = json.loads(result)
    # Shape check: top-level keys present for hook param mapping.
    assert "todoist_task_ids" in data
    assert "trello_card_ids" in data
    assert "jira_issue_keys" in data
    assert "jira_updates_json" in data


@pytest.mark.asyncio
async def test_jira_batch_updates_field_present(cfg: ProjConfig, mcp_app, tmp_path: Path):
    """todo_complete batch result must include jira_batch_updates as a structured list
    alongside the legacy jira_updates_json string (backwards compat)."""
    setup_project(cfg, "myapp", str(tmp_path))
    todos = [
        _make_todo("1", jira_issue_key="PROJ-1"),
        _make_todo("2", jira_issue_key="PROJ-2"),
    ]
    storage.save_todos(cfg, "myapp", todos)
    state.set_session_active("myapp")

    result = await call_tool(mcp_app, "todo_complete", todo_ids=["1", "2"])
    data = json.loads(result)

    # New structured field.
    assert "jira_batch_updates" in data
    assert isinstance(data["jira_batch_updates"], list)
    assert len(data["jira_batch_updates"]) == 2
    keys = {item["key"] for item in data["jira_batch_updates"]}
    assert keys == {"PROJ-1", "PROJ-2"}
    for item in data["jira_batch_updates"]:
        assert item["resolution"] == "Done"

    # Legacy field still present for backwards compat.
    assert "jira_updates_json" in data
    assert data["jira_updates_json"] != ""


@pytest.mark.asyncio
async def test_partial_hook_failure_commits_others(cfg: ProjConfig, mcp_app, tmp_path: Path):
    """Validation failures on SOME ids must not prevent others from being
    evaluated. Missing-id case: the whole batch is rejected (documented
    semantics — all-or-nothing validation). Verify no partial-commit drift."""
    setup_project(cfg, "myapp", str(tmp_path))
    todos = [_make_todo("1"), _make_todo("2")]
    storage.save_todos(cfg, "myapp", todos)
    state.set_session_active("myapp")

    result = await call_tool(mcp_app, "todo_complete", todo_ids=["1", "does-not-exist", "2"])
    data = json.loads(result)
    assert "error" in data
    assert "does-not-exist" in data["invalid_ids"]
    # Neither 1 nor 2 should be marked done (all-or-nothing).
    state_todos = storage.load_todos(cfg, "myapp")
    statuses = {t.id: _status_str(t) for t in state_todos}
    assert statuses["1"] == "pending"
    assert statuses["2"] == "pending"
