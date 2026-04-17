"""Tests for batch-add children via todo_add(parent=, children=) (children-only mode)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from server.lib import state, storage
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    RepoEntry,
    Todo,
)
from tests.conftest import call_tool


@pytest.fixture()
def project_with_parent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set up a project with a single root parent todo."""
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)

    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(cfg)

    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / "myapp"
    proj_dir.mkdir(parents=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "NOTES.md").write_text("# myapp\n")
    meta = ProjectMeta(
        name="myapp",
        repos=[RepoEntry(label="code", path=str(tmp_path))],
        dates=ProjectDates(created=today, last_updated=today),
    )
    storage.save_meta(cfg, meta)
    index = ProjectIndex(
        projects={"myapp": ProjectEntry(name="myapp", tracking_dir=str(proj_dir), created=today)},
    )
    storage.save_index(cfg, index)

    # Create a parent todo
    meta = storage.load_meta(cfg, "myapp")
    parent = Todo(
        id=str(meta.next_todo_id),
        title="Parent task",
        created=today,
        updated=today,
    )
    meta.next_todo_id += 1
    storage.save_meta(cfg, meta)
    storage.save_todos(cfg, "myapp", [parent])

    state.set_session_active("myapp")
    return cfg, "myapp", parent.id


@pytest.fixture()
def app(project_with_parent, cfg):
    """Return a configured FastMCP app."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, projects, todos

    # Use the cfg from project_with_parent fixture's monkeypatch
    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos.register(app)
    return app


@pytest.mark.asyncio
async def test_flat_children_created_atomically(project_with_parent):
    """Flat list of children created atomically in a single save."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, projects
    from server.tools import todos as todos_mod

    cfg, name, parent_id = project_with_parent
    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos_mod.register(app)

    children_json = json.dumps(
        [
            {"title": "Child A"},
            {"title": "Child B"},
            {"title": "Child C"},
        ]
    )

    result = await call_tool(app, "todo_add", parent=parent_id, children=children_json)
    data = json.loads(result)

    assert data["count"] == 3
    assert len(data["created"]) == 3
    assert data["created"][0]["title"] == "Child A"
    assert data["created"][1]["title"] == "Child B"
    assert data["created"][2]["title"] == "Child C"

    # Verify all children have the parent prefix in their IDs and group tag
    for item in data["created"]:
        assert item["id"].startswith(f"{parent_id}.")
        assert f"group:{parent_id}" in item.get("tags", [])

    # Verify on-disk state is consistent (single atomic save)
    todos = storage.load_todos(cfg, name)
    assert len(todos) == 4  # parent + 3 children
    child_todos = [t for t in todos if f"group:{parent_id}" in t.tags]
    assert len(child_todos) == 3


@pytest.mark.asyncio
async def test_nested_children_correct_ids(project_with_parent):
    """Nested children (parent with grandchildren) get correct hierarchical IDs."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, projects
    from server.tools import todos as todos_mod

    cfg, name, parent_id = project_with_parent
    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos_mod.register(app)

    # Child A has two sub-children
    children_json = json.dumps(
        [
            {
                "title": "Child A",
                "children": [
                    {"title": "Grandchild A1"},
                    {"title": "Grandchild A2"},
                ],
            },
            {"title": "Child B"},
        ]
    )

    result = await call_tool(app, "todo_add", parent=parent_id, children=children_json)
    data = json.loads(result)

    # Depth-first: Child A, Grandchild A1, Grandchild A2, Child B
    assert data["count"] == 4
    created = data["created"]
    assert created[0]["title"] == "Child A"
    assert created[1]["title"] == "Grandchild A1"
    assert created[2]["title"] == "Grandchild A2"
    assert created[3]["title"] == "Child B"

    # Child A is under parent_id
    child_a_id = created[0]["id"]
    assert child_a_id.startswith(f"{parent_id}.")
    assert f"group:{parent_id}" in created[0].get("tags", [])

    # Grandchildren are under Child A
    assert created[1]["id"].startswith(f"{child_a_id}.")
    assert f"group:{child_a_id}" in created[1].get("tags", [])
    assert created[2]["id"].startswith(f"{child_a_id}.")
    assert f"group:{child_a_id}" in created[2].get("tags", [])

    # Child B is under parent_id (sibling of Child A)
    assert f"group:{parent_id}" in created[3].get("tags", [])

    # Verify on-disk hierarchy via group tags
    todos = storage.load_todos(cfg, name)
    direct_children = [t for t in todos if f"group:{parent_id}" in t.tags]
    assert child_a_id in {t.id for t in direct_children}
    assert created[3]["id"] in {t.id for t in direct_children}
    grandchildren = [t for t in todos if f"group:{child_a_id}" in t.tags]
    assert created[1]["id"] in {t.id for t in grandchildren}
    assert created[2]["id"] in {t.id for t in grandchildren}


@pytest.mark.asyncio
async def test_blocking_pairs_link_created_todos(project_with_parent):
    """blocking_pairs correctly link created todos by depth-first index."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, projects
    from server.tools import todos as todos_mod

    cfg, name, parent_id = project_with_parent
    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos_mod.register(app)

    children_json = json.dumps(
        [
            {"title": "Setup"},
            {"title": "Build"},
            {"title": "Deploy"},
        ]
    )
    # Setup (idx 0) blocks Build (idx 1); Build (idx 1) blocks Deploy (idx 2)
    blocking_json = json.dumps([[0, 1], [1, 2]])

    result = await call_tool(
        app,
        "todo_add",
        parent=parent_id,
        children=children_json,
        blocking_pairs=blocking_json,
    )
    data = json.loads(result)
    assert data["count"] == 3
    assert "blocking_errors" not in data

    created = data["created"]
    setup_id = created[0]["id"]
    build_id = created[1]["id"]
    deploy_id = created[2]["id"]

    # Verify blocking relationships on disk
    todos = storage.load_todos(cfg, name)
    todo_map = {t.id: t for t in todos}

    setup_todo = todo_map[setup_id]
    build_todo = todo_map[build_id]
    deploy_todo = todo_map[deploy_id]

    assert build_id in setup_todo.blocks
    assert setup_id in build_todo.blocked_by
    assert deploy_id in build_todo.blocks
    assert build_id in deploy_todo.blocked_by


@pytest.mark.asyncio
async def test_invalid_parent_id_returns_error(project_with_parent):
    """Invalid parent returns an error message."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, projects
    from server.tools import todos as todos_mod

    cfg, name, _parent_id = project_with_parent
    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos_mod.register(app)

    children_json = json.dumps([{"title": "Orphan"}])

    result = await call_tool(app, "todo_add", parent="nonexistent-99", children=children_json)
    assert "not found" in result.lower()

    # Verify nothing was written
    todos = storage.load_todos(cfg, name)
    assert len(todos) == 1  # only the original parent


@pytest.mark.asyncio
async def test_empty_children_list_returns_error(project_with_parent):
    """Empty children list returns an error."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, projects
    from server.tools import todos as todos_mod

    cfg, name, parent_id = project_with_parent
    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos_mod.register(app)

    result = await call_tool(app, "todo_add", parent=parent_id, children="[]")
    assert "non-empty" in result.lower()

    # Verify nothing changed
    todos = storage.load_todos(cfg, name)
    assert len(todos) == 1


@pytest.mark.asyncio
async def test_nested_todoist_tasks_parent_index(project_with_parent):
    """Todoist tasks get correct _parent_index for grandchildren."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, projects
    from server.tools import todos as todos_mod

    cfg, name, parent_id = project_with_parent

    # Set todoist IDs on the meta and parent todo so todoist_tasks are built
    meta = storage.load_meta(cfg, name)
    meta.todoist_project_id = "proj-123"
    storage.save_meta(cfg, meta)

    todos_list = storage.load_todos(cfg, name)
    parent_todo = next(t for t in todos_list if t.id == parent_id)
    parent_todo.todoist_task_id = "todoist-parent-99"
    storage.save_todos(cfg, name, todos_list)

    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos_mod.register(app)

    # 3-level nesting: parent → child A → grandchild A1
    children_json = json.dumps(
        [
            {
                "title": "Child A",
                "children": [
                    {"title": "Grandchild A1"},
                ],
            },
            {"title": "Child B"},
        ]
    )

    result = await call_tool(app, "todo_add", parent=parent_id, children=children_json)
    data = json.loads(result)

    todoist_tasks = data["todoist_tasks"]
    assert len(todoist_tasks) == 3

    # Child A: direct child → parentId = root's todoist ID, _parent_index = -1
    assert todoist_tasks[0]["content"] == "Child A"
    assert todoist_tasks[0]["parentId"] == "todoist-parent-99"
    assert todoist_tasks[0]["_parent_index"] == -1

    # Grandchild A1: child of Child A → no parentId, _parent_index = 0 (index of Child A)
    assert todoist_tasks[1]["content"] == "Grandchild A1"
    assert "parentId" not in todoist_tasks[1]
    assert todoist_tasks[1]["_parent_index"] == 0

    # Child B: direct child → parentId = root's todoist ID, _parent_index = -1
    assert todoist_tasks[2]["content"] == "Child B"
    assert todoist_tasks[2]["parentId"] == "todoist-parent-99"
    assert todoist_tasks[2]["_parent_index"] == -1


@pytest.mark.asyncio
async def test_invalid_json_returns_error(project_with_parent):
    """Invalid JSON for children parameter returns an error."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, projects
    from server.tools import todos as todos_mod

    _cfg, _name, parent_id = project_with_parent
    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos_mod.register(app)

    result = await call_tool(app, "todo_add", parent=parent_id, children="{not valid json")
    assert "invalid json" in result.lower()

    # Also test invalid blocking_pairs JSON
    children_json = json.dumps([{"title": "Valid child"}])
    result2 = await call_tool(
        app,
        "todo_add",
        parent=parent_id,
        children=children_json,
        blocking_pairs="{bad}",
    )
    assert "invalid json" in result2.lower()
