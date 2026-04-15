"""Tests for folding todo_block/todo_unblock into todo_update(blocked_by_set=)."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from mcp.server.fastmcp import FastMCP

from server.lib import state, storage
from server.lib.models import ProjConfig, Todo
from tests.conftest import call_tool, setup_project


def _make_todo(tid: str, title: str = "Task") -> Todo:
    today = str(date.today())
    return Todo(id=tid, title=title, created=today, updated=today, status="pending")


def test_todo_block_unblock_tools_removed():
    from mcp.server.fastmcp import FastMCP

    from server.tools.todos import register

    app = FastMCP("test")
    register(app)
    tool_names = [t.name for t in app._tool_manager.list_tools()]
    assert "todo_block" not in tool_names
    assert "todo_unblock" not in tool_names
    assert "todo_update" in tool_names


@pytest.mark.asyncio
async def test_todo_update_blocked_by_set_replaces_blockers(cfg: ProjConfig, tmp_path: Path):
    """blocked_by_set replaces existing blockers and updates inverse blocks lists."""
    from server.tools import config, projects, todos

    setup_project(cfg, "myapp", str(tmp_path))

    # A blocked by B initially; we'll replace with C
    a = _make_todo("A")
    b = _make_todo("B")
    c = _make_todo("C")
    # Set initial state: A blocked_by B, B blocks A
    a.blocked_by = ["B"]
    b.blocks = ["A"]
    storage.save_todos(cfg, "myapp", [a, b, c])
    state.set_session_active("myapp")

    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos.register(app)

    result = await call_tool(app, "todo_update", todo_id="A", blocked_by_set=["C"])
    data = json.loads(result)
    assert "error" not in data

    loaded = storage.load_todos(cfg, "myapp")
    todo_map = {t.id: t for t in loaded}

    assert todo_map["A"].blocked_by == ["C"]
    assert "A" in todo_map["C"].blocks
    assert "A" not in todo_map["B"].blocks


@pytest.mark.asyncio
async def test_todo_update_blocked_by_set_empty_clears_blockers(cfg: ProjConfig, tmp_path: Path):
    """blocked_by_set=[] removes all blockers (equivalent to old todo_unblock)."""
    from server.tools import config, projects, todos

    setup_project(cfg, "myapp", str(tmp_path))

    a = _make_todo("A")
    b = _make_todo("B")
    a.blocked_by = ["B"]
    b.blocks = ["A"]
    storage.save_todos(cfg, "myapp", [a, b])
    state.set_session_active("myapp")

    app = FastMCP("test-proj")
    config.register(app)
    projects.register(app)
    todos.register(app)

    result = await call_tool(app, "todo_update", todo_id="A", blocked_by_set=[])
    data = json.loads(result)
    assert "error" not in data

    loaded = storage.load_todos(cfg, "myapp")
    todo_map = {t.id: t for t in loaded}

    assert todo_map["A"].blocked_by == []
    assert "A" not in todo_map["B"].blocks
