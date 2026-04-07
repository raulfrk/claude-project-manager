"""Tests for todo_batch_add_children MCP tool."""

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

    result = await call_tool(
        app, "todo_batch_add_children", parent_id=parent_id, children=children_json
    )
    data = json.loads(result)

    assert data["count"] == 3
    assert len(data["created"]) == 3
    assert data["created"][0]["title"] == "Child A"
    assert data["created"][1]["title"] == "Child B"
    assert data["created"][2]["title"] == "Child C"

    # Verify all children have the parent prefix in their IDs
    for item in data["created"]:
        assert item["id"].startswith(f"{parent_id}.")
        assert item["parent"] == parent_id

    # Verify on-disk state is consistent (single atomic save)
    todos = storage.load_todos(cfg, name)
    assert len(todos) == 4  # parent + 3 children
    parent_todo = next(t for t in todos if t.id == parent_id)
    assert len(parent_todo.children) == 3


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

    result = await call_tool(
        app, "todo_batch_add_children", parent_id=parent_id, children=children_json
    )
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
    assert created[0]["parent"] == parent_id

    # Grandchildren are under Child A
    assert created[1]["id"].startswith(f"{child_a_id}.")
    assert created[1]["parent"] == child_a_id
    assert created[2]["id"].startswith(f"{child_a_id}.")
    assert created[2]["parent"] == child_a_id

    # Child B is under parent_id (sibling of Child A)
    assert created[3]["parent"] == parent_id

    # Verify on-disk hierarchy
    todos = storage.load_todos(cfg, name)
    parent_todo = next(t for t in todos if t.id == parent_id)
    child_a_todo = next(t for t in todos if t.id == child_a_id)
    assert child_a_id in parent_todo.children
    assert created[3]["id"] in parent_todo.children
    assert created[1]["id"] in child_a_todo.children
    assert created[2]["id"] in child_a_todo.children


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
        "todo_batch_add_children",
        parent_id=parent_id,
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
    """Invalid parent_id returns an error message."""
    from mcp.server.fastmcp import FastMCP

    from server.tools import config, projects
    from server.tools import todos as todos_mod

    cfg, name, _parent_id = project_with_parent
    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos_mod.register(app)

    children_json = json.dumps([{"title": "Orphan"}])

    result = await call_tool(
        app, "todo_batch_add_children", parent_id="nonexistent-99", children=children_json
    )
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

    result = await call_tool(app, "todo_batch_add_children", parent_id=parent_id, children="[]")
    assert "non-empty" in result.lower()

    # Verify nothing changed
    todos = storage.load_todos(cfg, name)
    assert len(todos) == 1


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

    result = await call_tool(
        app, "todo_batch_add_children", parent_id=parent_id, children="{not valid json"
    )
    assert "invalid json" in result.lower()

    # Also test invalid blocking_pairs JSON
    children_json = json.dumps([{"title": "Valid child"}])
    result2 = await call_tool(
        app,
        "todo_batch_add_children",
        parent_id=parent_id,
        children=children_json,
        blocking_pairs="{bad}",
    )
    assert "invalid json" in result2.lower()
