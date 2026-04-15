"""Tests for consolidated todo_add (replaces todo_add_child, todo_batch_add_children)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import ProjConfig
from tests.conftest import call_tool, setup_project


def get_registered_tool_names(app):
    """Helper to get all registered tool names from a FastMCP app."""
    return [t.name for t in app._tool_manager.list_tools()]


@pytest.fixture()
def project(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str]:
    setup_project(cfg, "myapp", str(tmp_path))
    state.set_session_active("myapp")
    return cfg, "myapp"


def test_todo_add_child_tool_does_not_exist():
    """todo_add_child must not be registered — use todo_add(parent=) instead."""
    from mcp.server.fastmcp import FastMCP

    from server.tools.todos import register

    app = FastMCP("test")
    register(app)
    tool_names = get_registered_tool_names(app)
    assert "todo_add_child" not in tool_names, (
        "todo_add_child is still registered — it should be removed; use todo_add(parent=) instead"
    )
    assert "todo_add" in tool_names


@pytest.mark.asyncio
async def test_todo_add_with_parent_creates_child_id(
    mcp_app: Any,
    project: tuple[ProjConfig, str],
) -> None:
    """todo_add(parent=) creates a child todo with dot-notation ID under the parent."""
    # Create parent
    r_parent = json.loads(
        await call_tool(mcp_app, "todo_add", title="Parent", project_name="myapp")
    )
    assert "todo_id" in r_parent
    parent_id = r_parent["todo_id"]

    # Create child via todo_add(parent=)
    r_child = json.loads(
        await call_tool(mcp_app, "todo_add", title="Child", parent=parent_id, project_name="myapp")
    )
    assert "todo_id" in r_child, f"Expected todo_id in response, got: {r_child}"
    child_id = r_child["todo_id"]

    # Child ID must be a sub-id of parent
    assert child_id.startswith(f"{parent_id}."), (
        f"Expected child ID to start with '{parent_id}.', got '{child_id}'"
    )

    # Parent must list child in children field
    cfg, name = project
    todos = storage.load_todos(cfg, name)
    parent_todo = next(t for t in todos if t.id == parent_id)
    assert child_id in parent_todo.children, (
        f"Expected '{child_id}' in parent.children, got {parent_todo.children}"
    )


def test_todo_batch_add_children_tool_does_not_exist():
    """todo_batch_add_children must not be registered — use todo_add(children=) instead."""
    from mcp.server.fastmcp import FastMCP

    from server.tools.todos import register

    app = FastMCP("test")
    register(app)
    tool_names = get_registered_tool_names(app)
    assert "todo_batch_add_children" not in tool_names, (
        "todo_batch_add_children is still registered — fold into todo_add(children=)"
    )
    assert "todo_add" in tool_names


@pytest.mark.asyncio
async def test_todo_add_children_only_mode(
    mcp_app: Any,
    project: tuple[ProjConfig, str],
) -> None:
    """todo_add with parent= + children= but no title adds children to existing parent."""
    # Create parent
    r_parent = json.loads(
        await call_tool(mcp_app, "todo_add", title="Parent Todo", project_name="myapp")
    )
    assert "todo_id" in r_parent
    parent_id = r_parent["todo_id"]

    # Children-only mode: no title, parent= + children=
    children_json = json.dumps([{"title": "child 1"}, {"title": "child 2"}])
    r_batch = json.loads(
        await call_tool(
            mcp_app,
            "todo_add",
            parent=parent_id,
            children=children_json,
            project_name="myapp",
        )
    )

    # Assert result contains created_ids / count
    assert "created_ids" in r_batch or "created" in r_batch, (
        f"Expected 'created_ids' or 'created' in response, got: {r_batch}"
    )
    created = r_batch.get("created_ids") or [c["id"] for c in r_batch.get("created", [])]
    assert len(created) == 2, f"Expected 2 children created, got: {created}"

    # Assert parent's children list now has 2 entries
    cfg, name = project
    todos = storage.load_todos(cfg, name)
    parent_todo = next(t for t in todos if t.id == parent_id)
    assert len(parent_todo.children) == 2, (
        f"Expected 2 children on parent, got: {parent_todo.children}"
    )

    # Assert no extra root todo was created (only parent + 2 children = 3 total)
    root_todos = [t for t in todos if t.parent is None]
    assert len(root_todos) == 1, (
        f"Expected only 1 root todo (the parent), got {len(root_todos)}: "
        f"{[t.id for t in root_todos]}"
    )
