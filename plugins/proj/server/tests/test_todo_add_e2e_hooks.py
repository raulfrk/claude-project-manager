"""End-to-end hook-dispatch integration tests for todo_add (task 624).

These tests exercise the full payload chain:
  todo_add → _todo_hook_fields → hook dispatch source_result

The hook dispatch layer (router) is not running in the test environment, so we
monkeypatch `hook_dispatch.dispatch._dispatch_hook` to capture the serialized
source_result that would be POSTed to the router. Assertions then verify that:

- Task 3: parent_jira_issue_key is emitted for flat children
- Task 4: synced_tags strips group:* entries
- Task 5: omit_if_empty — top-level todo has no parent_jira_issue_key field
           (meaning the router's omit_if_empty DSL would drop parent_key)
- Task 6: Jira hook param_mapping references correct parent field name
- Task 7: Todoist hook param_mapping uses synced_tags (not raw tags)
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from hook_dispatch import enable_hook_dispatch
from mcp.server.fastmcp import FastMCP

from server.lib import state, storage
from server.lib.models import (
    JiraSync,
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectMeta,
    RepoEntry,
    Todo,
    TodoistSync,
)
from tests.conftest import call_tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TODAY = str(date.today())


def _make_todo(tid: str, **kwargs: Any) -> Todo:
    defaults: dict[str, Any] = {
        "id": tid,
        "title": f"todo {tid}",
        "created": TODAY,
        "updated": TODAY,
    }
    defaults.update(kwargs)
    return Todo(**defaults)


def _save_todos(cfg: ProjConfig, name: str, todos: list[Todo]) -> None:
    """Save todos and bump meta.next_todo_id past the highest existing numeric id.

    Without this, todo_add would re-generate the same numeric id as the seeded
    parent and hit a UNIQUE constraint on the second insert.
    """
    storage.save_todos(cfg, name, todos)
    meta = storage.load_meta(cfg, name)
    max_id = 0
    for t in todos:
        try:
            numeric = int(t.id.split(".")[0])
            max_id = max(max_id, numeric)
        except (ValueError, AttributeError):
            pass
    if max_id >= meta.next_todo_id:
        meta.next_todo_id = max_id + 1
        storage.save_meta(cfg, meta)


def _setup_integration_project(
    cfg: ProjConfig,
    name: str,
    tmp_path: Path,
    *,
    todoist_project_id: str = "PROJ-T",
    jira_issue_key: str = "CPM-0",
) -> None:
    """Create a project with Todoist + Jira integration IDs set."""
    today = TODAY
    proj_dir = Path(cfg.tracking_dir) / name
    proj_dir.mkdir(parents=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "NOTES.md").write_text(f"# {name}\n")
    meta = ProjectMeta(
        name=name,
        repos=[RepoEntry(label="code", path=str(tmp_path))],
        dates=ProjectDates(created=today, last_updated=today),
        todoist_project_id=todoist_project_id,
        jira_issue_key=jira_issue_key,
    )
    storage.save_meta(cfg, meta)
    index = storage.load_index(cfg)
    index.projects[name] = ProjectEntry(name=name, tracking_dir=str(proj_dir), created=today)
    storage.save_index(cfg, index)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def cfg_with_integrations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjConfig:
    """ProjConfig with Todoist + Jira integration enabled."""
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)
    cfg = ProjConfig(
        tracking_dir=str(tmp_path / "tracking"),
        todoist=TodoistSync(enabled=True, auto_sync=True),
        jira=JiraSync(enabled=True, auto_sync=True),
    )
    storage.save_config(cfg)
    return cfg


@pytest.fixture()
def app_with_hooks(cfg_with_integrations: ProjConfig) -> tuple[FastMCP, list[dict[str, Any]]]:
    """FastMCP app with hook_dispatch enabled; captures dispatched payloads."""
    from server.tools import config, projects, todos

    dispatched: list[dict[str, Any]] = []

    async def _fake_dispatch(
        tool_name: str,
        result: Any,
        hooks_port: int = 19100,
    ) -> dict[str, Any] | None:
        # Serialize the result exactly as the real dispatcher would, then capture it.
        from hook_dispatch.dispatch import _serialize_result  # type: ignore[import-not-found]

        serialized = _serialize_result(result)
        dispatched.append({"tool_name": tool_name, "source_result": json.loads(serialized)})
        return {"hooks_fired": 0, "errors": [], "results": []}

    app = FastMCP("test-proj-hooks")
    # Patch _dispatch_hook before enable_hook_dispatch wraps the tools, so the
    # wrapper calls our fake instead of the real httpx call.
    with patch("hook_dispatch.dispatch._dispatch_hook", new=_fake_dispatch):
        enable_hook_dispatch(app)
        config.register(app)
        projects.register(app)
        todos.register(app)

    return app, dispatched


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_e2e_flat_child_fires_todoist_hook_with_parent_id(
    cfg_with_integrations: ProjConfig,
    app_with_hooks: tuple[FastMCP, list[dict[str, Any]]],
    tmp_path: Path,
) -> None:
    """Flat child todo_add result carries parent_todoist_task_id + synced_tags strips group:*.

    Chain validated:
      Task 3 — parent_todoist_task_id emitted from group:* tag resolution
      Task 4 — synced_tags has no group:* entries
      Task 7 — Todoist hook mapping references synced_tags (not raw tags)
    """
    cfg = cfg_with_integrations
    app, dispatched = app_with_hooks
    name = "myapp"
    _setup_integration_project(cfg, name, tmp_path, todoist_project_id="PROJ-T")

    # Seed parent with known Todoist task ID.
    parent = _make_todo("1", title="parent", todoist_task_id="PAR-T-ID")
    _save_todos(cfg, name, [parent])
    state.set_session_active(name)

    # Patch _dispatch_hook at the module level so the wrapped tool calls our fake.
    dispatched.clear()
    with patch("hook_dispatch.dispatch._dispatch_hook") as mock_dispatch:
        mock_dispatch.return_value = {"hooks_fired": 0, "errors": [], "results": []}

        result_str = await call_tool(
            app,
            "todo_add",
            title="child task",
            tags=["group:1", "feature"],
            project_name=name,
        )

    data = json.loads(result_str)
    assert "error" not in data, f"todo_add returned error: {data}"

    # Task 3: parent_todoist_task_id must be present and equal parent's todoist id.
    assert data.get("parent_todoist_task_id") == "PAR-T-ID", (
        f"parent_todoist_task_id not emitted; got: {data}"
    )

    # Task 4: synced_tags must not contain any group:* entries.
    synced = data.get("synced_tags", [])
    group_entries = [t for t in synced if t.startswith("group:")]
    assert group_entries == [], f"synced_tags still contains group:* entries: {synced}"
    assert "feature" in synced, f"non-group tag 'feature' missing from synced_tags: {synced}"

    # Task 7: raw tags field still has group:1 so hook diff is traceable.
    assert "group:1" in data.get("tags", []), "raw tags field must preserve group:1"


@pytest.mark.asyncio
async def test_e2e_flat_child_fires_jira_hook_with_epic_parent_key(
    cfg_with_integrations: ProjConfig,
    app_with_hooks: tuple[FastMCP, list[dict[str, Any]]],
    tmp_path: Path,
) -> None:
    """Flat child todo_add result carries parent_jira_issue_key + synced_tags strips group:*.

    Chain validated:
      Task 3 — parent_jira_issue_key emitted from group:* tag resolution
      Task 4 — synced_tags has no group:* entries
      Task 6 — Jira hook param_mapping can resolve parent_key from parent_jira_issue_key
    """
    cfg = cfg_with_integrations
    app, _dispatched = app_with_hooks
    name = "myapp2"
    _setup_integration_project(cfg, name, tmp_path, jira_issue_key="CPM-0")

    # Seed parent with known Jira issue key.
    parent = _make_todo("10", title="epic parent", jira_issue_key="CPM-100")
    _save_todos(cfg, name, [parent])
    state.set_session_active(name)

    with patch("hook_dispatch.dispatch._dispatch_hook") as mock_dispatch:
        mock_dispatch.return_value = {"hooks_fired": 0, "errors": [], "results": []}

        result_str = await call_tool(
            app,
            "todo_add",
            title="child story",
            tags=["group:10", "backend"],
            project_name=name,
        )

    data = json.loads(result_str)
    assert "error" not in data, f"todo_add returned error: {data}"

    # Task 3 / Task 6: parent_jira_issue_key present → router resolves ${parent_jira_issue_key}
    # into parent_key in jira_create_issue call.
    assert data.get("parent_jira_issue_key") == "CPM-100", (
        f"parent_jira_issue_key not emitted; got: {data}"
    )

    # Task 4: synced_tags strips group:* entries.
    synced = data.get("synced_tags", [])
    group_entries = [t for t in synced if t.startswith("group:")]
    assert group_entries == [], f"synced_tags still contains group:* entries: {synced}"
    assert "backend" in synced, f"non-group tag 'backend' missing from synced_tags: {synced}"

    # Task 6: Jira hook param_mapping `parent_key` uses ${parent_jira_issue_key}.
    # Validate the contract: if data has parent_jira_issue_key, the omit_if_empty directive
    # in jira-on-todo-add would NOT drop parent_key — it would pass "CPM-100" through.
    assert data["parent_jira_issue_key"]  # truthy → omit_if_empty would keep the field


@pytest.mark.asyncio
async def test_e2e_top_level_flat_todo_fires_jira_hook_without_parent_key(
    cfg_with_integrations: ProjConfig,
    app_with_hooks: tuple[FastMCP, list[dict[str, Any]]],
    tmp_path: Path,
) -> None:
    """Top-level todo result has no parent_jira_issue_key → omit_if_empty drops parent_key.

    Chain validated:
      Task 5 — omit_if_empty: true on jira-on-todo-add's parent_key mapping
               When parent_jira_issue_key is absent from source_result, the router's
               omit_if_empty DSL drops parent_key from the jira_create_issue call entirely.
    """
    cfg = cfg_with_integrations
    app, _ = app_with_hooks
    name = "myapp3"
    _setup_integration_project(cfg, name, tmp_path, jira_issue_key="CPM-0")
    state.set_session_active(name)

    with patch("hook_dispatch.dispatch._dispatch_hook") as mock_dispatch:
        mock_dispatch.return_value = {"hooks_fired": 0, "errors": [], "results": []}

        result_str = await call_tool(
            app,
            "todo_add",
            title="standalone task",
            project_name=name,
        )

    data = json.loads(result_str)
    assert "error" not in data, f"todo_add returned error: {data}"

    # Task 5 / Task 6: top-level todo must NOT have parent_jira_issue_key in source_result.
    # When this field is absent (or None/empty), the router's omit_if_empty: true directive
    # on jira-on-todo-add param_mapping.parent_key drops the field entirely — so the Jira
    # create request has no parent_key, preventing an invalid Jira subtask linkage.
    assert "parent_jira_issue_key" not in data, (
        f"top-level todo must not emit parent_jira_issue_key; got: {data}"
    )

    # Also verify: no parent_todoist_task_id (same omit logic applies to Todoist).
    assert "parent_todoist_task_id" not in data, (
        f"top-level todo must not emit parent_todoist_task_id; got: {data}"
    )

    # Task 4: synced_tags present and empty-or-no-group (no tags were passed).
    synced = data.get("synced_tags", [])
    group_entries = [t for t in synced if t.startswith("group:")]
    assert group_entries == [], f"synced_tags must not contain group:* entries: {synced}"
