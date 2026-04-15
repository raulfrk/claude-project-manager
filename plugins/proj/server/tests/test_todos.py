"""Tests for todo operations via storage layer."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from server.lib import storage
from server.lib.ids import next_todo_id
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    RepoEntry,
    Todo,
)
from server.tools.todos import _normalize_title


@pytest.fixture()
def cfg_with_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ProjConfig, str]:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)

    cfg = ProjConfig(tracking_dir=str(tmp_path / "tracking"))
    storage.save_config(cfg)

    # Create project
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
    return cfg, "myapp"


def _make_todo(meta: ProjectMeta, title: str, **kwargs: object) -> Todo:
    today = str(date.today())
    todo = Todo(id=next_todo_id(meta), title=title, created=today, updated=today)
    for k, v in kwargs.items():
        setattr(todo, k, v)
    return todo


class TestTodoCRUD:
    def test_add_todo(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        todo = _make_todo(meta, "Do something")
        storage.save_meta(cfg, meta)
        storage.save_todos(cfg, name, [todo])
        todos = storage.load_todos(cfg, name)
        assert len(todos) == 1
        assert todos[0].id == "1"
        assert todos[0].title == "Do something"

    def test_complete_todo(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        todo = _make_todo(meta, "Task")
        storage.save_meta(cfg, meta)
        storage.save_todos(cfg, name, [todo])

        todos = storage.load_todos(cfg, name)
        todos[0].status = "done"
        storage.save_todos(cfg, name, todos)

        todos = storage.load_todos(cfg, name)
        assert todos[0].status == "done"

    def test_nested_todos(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        parent = _make_todo(meta, "Parent task")
        child = _make_todo(meta, "Child task", parent=parent.id)
        parent.children.append(child.id)
        storage.save_meta(cfg, meta)
        storage.save_todos(cfg, name, [parent, child])

        todos = storage.load_todos(cfg, name)
        assert len(todos) == 2
        parent_loaded = next(t for t in todos if t.id == parent.id)
        child_loaded = next(t for t in todos if t.id == child.id)
        assert child_loaded.id in parent_loaded.children
        assert child_loaded.parent == parent.id

    def test_blocking_relationships(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        t1 = _make_todo(meta, "Task 1")
        t2 = _make_todo(meta, "Task 2")
        # t1 blocks t2
        t1.blocks.append(t2.id)
        t2.blocked_by.append(t1.id)
        storage.save_meta(cfg, meta)
        storage.save_todos(cfg, name, [t1, t2])

        todos = storage.load_todos(cfg, name)
        assert t2.id in todos[0].blocks
        assert t1.id in todos[1].blocked_by

    def test_ready_todos_filter(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        t_ready = _make_todo(meta, "Ready")
        t_blocked = _make_todo(meta, "Blocked", blocked_by=["1"])
        storage.save_meta(cfg, meta)
        storage.save_todos(cfg, name, [t_ready, t_blocked])

        todos = storage.load_todos(cfg, name)
        ready = [t for t in todos if t.status == "pending" and not t.blocked_by]
        assert len(ready) == 1
        assert ready[0].title == "Ready"

    def test_todo_id_sequence(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        ids = [next_todo_id(meta) for _ in range(5)]
        assert ids == ["1", "2", "3", "4", "5"]


class TestNextTodoId:
    """Unit tests for next_todo_id() covering root, child, and deep-nesting cases."""

    def test_root_id_starts_at_one(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        tid = next_todo_id(meta)
        assert tid == "1"

    def test_root_id_increments_meta_counter(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        next_todo_id(meta)
        next_todo_id(meta)
        assert meta.next_todo_id == 3

    def test_child_id_uses_parent_prefix(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        today = str(__import__("datetime").date.today())
        parent = Todo(id="3", title="Parent", created=today, updated=today)
        child_id = next_todo_id(meta, parent=parent)
        assert child_id == "3.1"

    def test_child_id_increments_parent_counter(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        today = str(__import__("datetime").date.today())
        parent = Todo(id="2", title="Parent", created=today, updated=today)
        next_todo_id(meta, parent=parent)
        next_todo_id(meta, parent=parent)
        assert parent.next_child_id == 3

    def test_child_id_does_not_increment_meta_counter(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        today = str(__import__("datetime").date.today())
        parent = Todo(id="1", title="Parent", created=today, updated=today)
        before = meta.next_todo_id
        next_todo_id(meta, parent=parent)
        assert meta.next_todo_id == before

    def test_deep_nesting_three_levels(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        today = str(__import__("datetime").date.today())
        # Root todo: ID "1"
        root = Todo(id=next_todo_id(meta), title="Root", created=today, updated=today)
        assert root.id == "1"
        # Child todo: ID "1.1"
        child = Todo(
            id=next_todo_id(meta, parent=root), title="Child", created=today, updated=today
        )
        assert child.id == "1.1"
        # Grandchild todo: ID "1.1.1"
        grandchild_id = next_todo_id(meta, parent=child)
        assert grandchild_id == "1.1.1"

    def test_multiple_children_get_sequential_suffixes(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        today = str(__import__("datetime").date.today())
        parent = Todo(id="5", title="Parent", created=today, updated=today)
        ids = [next_todo_id(meta, parent=parent) for _ in range(4)]
        assert ids == ["5.1", "5.2", "5.3", "5.4"]

    def test_deep_nesting_five_levels(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        today = str(__import__("datetime").date.today())
        root = Todo(id=next_todo_id(meta), title="Root", created=today, updated=today)
        assert root.id == "1"
        child = Todo(
            id=next_todo_id(meta, parent=root), title="Child", created=today, updated=today
        )
        assert child.id == "1.1"
        grandchild = Todo(
            id=next_todo_id(meta, parent=child), title="Grandchild", created=today, updated=today
        )
        assert grandchild.id == "1.1.1"
        great = Todo(
            id=next_todo_id(meta, parent=grandchild),
            title="Great-grandchild",
            created=today,
            updated=today,
        )
        assert great.id == "1.1.1.1"
        great_great_id = next_todo_id(meta, parent=great)
        assert great_great_id == "1.1.1.1.1"
        # Meta counter only incremented once (for root)
        assert meta.next_todo_id == 2

    def test_deep_nesting_sibling_counters_are_independent(
        self, cfg_with_project: tuple[ProjConfig, str]
    ) -> None:
        cfg, name = cfg_with_project
        meta = storage.load_meta(cfg, name)
        today = str(__import__("datetime").date.today())
        root = Todo(id=next_todo_id(meta), title="Root", created=today, updated=today)
        child_a = Todo(
            id=next_todo_id(meta, parent=root), title="Child A", created=today, updated=today
        )
        child_b = Todo(
            id=next_todo_id(meta, parent=root), title="Child B", created=today, updated=today
        )
        assert child_a.id == "1.1"
        assert child_b.id == "1.2"
        # Each child has its own independent counter
        gc_a1 = next_todo_id(meta, parent=child_a)
        gc_a2 = next_todo_id(meta, parent=child_a)
        gc_b1 = next_todo_id(meta, parent=child_b)
        assert gc_a1 == "1.1.1"
        assert gc_a2 == "1.1.2"
        assert gc_b1 == "1.2.1"


class TestContent:
    def test_requirements_write_read(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        storage.write_requirements(cfg, name, "T001", "# Goals\nDo X")
        content = storage.read_requirements(cfg, name, "T001")
        assert content is not None
        assert "Do X" in content

    def test_research_missing_returns_none(self, cfg_with_project: tuple[ProjConfig, str]) -> None:
        cfg, name = cfg_with_project
        result = storage.read_research(cfg, name, "T999")
        assert result is None

    def test_claudemd_write_read(self, tmp_path: Path) -> None:
        storage.write_claudemd(str(tmp_path), "# My Project\n\nStatus: active")
        content = storage.read_claudemd(str(tmp_path))
        assert content is not None
        assert "Status: active" in content


class TestNormalizeTitle:
    def test_lowercases(self) -> None:
        assert _normalize_title("Fix Bug") == "fix bug"

    def test_collapses_whitespace(self) -> None:
        assert _normalize_title("fix  bug") == "fix bug"

    def test_strips_leading_trailing(self) -> None:
        assert _normalize_title("  fix bug  ") == "fix bug"

    def test_combined(self) -> None:
        assert _normalize_title("  Fix   Bug  ") == "fix bug"


@pytest.mark.asyncio
class TestTodoAddDedup:
    """Dedup guard tests for todo_add, todo_add_child, and todo_batch_add_children."""

    @pytest.fixture()
    def app(self, cfg_with_project: tuple[ProjConfig, str]) -> Any:
        from mcp.server.fastmcp import FastMCP

        from server.tools import config as config_mod
        from server.tools import projects
        from server.tools import todos as todos_mod

        app = FastMCP("test-dedup")
        config_mod.register(app)
        projects.register(app)
        todos_mod.register(app)
        return app

    async def _call(self, app: Any, tool: str, **kwargs: object) -> dict:
        from tests.conftest import call_tool

        raw = await call_tool(app, tool, **kwargs)
        return json.loads(raw)

    async def test_todo_add_rejects_duplicate_title(
        self,
        app: Any,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        r1 = await self._call(
            app,
            "todo_add",
            title="Fix bug",
            project_name="myapp",
        )
        assert "todo_id" in r1
        r2 = await self._call(
            app,
            "todo_add",
            title="Fix bug",
            project_name="myapp",
        )
        assert "error" in r2
        assert r2["existing_id"] == r1["todo_id"]

    async def test_todo_add_accepts_different_title(
        self,
        app: Any,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        r1 = await self._call(
            app,
            "todo_add",
            title="Fix bug",
            project_name="myapp",
        )
        assert "todo_id" in r1
        r2 = await self._call(
            app,
            "todo_add",
            title="Fix typo",
            project_name="myapp",
        )
        assert "todo_id" in r2
        assert r1["todo_id"] != r2["todo_id"]

    async def test_todo_add_normalized_title_match(
        self,
        app: Any,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        r1 = await self._call(
            app,
            "todo_add",
            title="Fix Bug",
            project_name="myapp",
        )
        assert "todo_id" in r1
        r2 = await self._call(
            app,
            "todo_add",
            title="fix  bug",
            project_name="myapp",
        )
        assert "error" in r2
        assert r2["existing_id"] == r1["todo_id"]

    async def test_todo_add_force_create_bypasses_dedup(
        self,
        app: Any,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        r1 = await self._call(
            app,
            "todo_add",
            title="Fix bug",
            project_name="myapp",
        )
        assert "todo_id" in r1
        r2 = await self._call(
            app,
            "todo_add",
            title="Fix bug",
            project_name="myapp",
            force_create=True,
        )
        assert "todo_id" in r2
        assert r1["todo_id"] != r2["todo_id"]

    async def test_todo_add_done_todo_not_blocking(
        self,
        app: Any,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        r1 = await self._call(
            app,
            "todo_add",
            title="Fix bug",
            project_name="myapp",
        )
        assert "todo_id" in r1
        # Mark it done via storage
        todos = storage.load_todos(cfg, name)
        todos[0].status = "done"
        storage.save_todos(cfg, name, todos)
        # Now adding same title should succeed
        r2 = await self._call(
            app,
            "todo_add",
            title="Fix bug",
            project_name="myapp",
        )
        assert "todo_id" in r2

    async def test_todo_add_different_parent_allowed(
        self,
        app: Any,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        p1 = await self._call(
            app,
            "todo_add",
            title="Parent A",
            project_name="myapp",
        )
        p2 = await self._call(
            app,
            "todo_add",
            title="Parent B",
            project_name="myapp",
        )
        r1 = await self._call(
            app,
            "todo_add",
            title="X",
            parent=p1["todo_id"],
            project_name="myapp",
        )
        assert "todo_id" in r1
        # Same title under different parent — should succeed
        r2 = await self._call(
            app,
            "todo_add",
            title="X",
            parent=p2["todo_id"],
            project_name="myapp",
        )
        assert "todo_id" in r2

    async def test_todo_add_child_rejects_duplicate(
        self,
        app: Any,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        p = await self._call(
            app,
            "todo_add",
            title="Parent",
            project_name="myapp",
        )
        r1 = await self._call(
            app,
            "todo_add",
            parent=p["todo_id"],
            title="Sub",
            project_name="myapp",
        )
        assert "todo_id" in r1
        r2 = await self._call(
            app,
            "todo_add",
            parent=p["todo_id"],
            title="Sub",
            project_name="myapp",
        )
        assert "error" in r2
        assert r2["existing_id"] == r1["todo_id"]

    async def test_todo_batch_add_children_skips_duplicates(
        self,
        app: Any,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        p = await self._call(
            app,
            "todo_add",
            title="Parent",
            project_name="myapp",
        )
        children = json.dumps(
            [
                {"title": "A"},
                {"title": "B"},
                {"title": "A"},
            ]
        )
        r = await self._call(
            app,
            "todo_batch_add_children",
            parent_id=p["todo_id"],
            children=children,
            project_name="myapp",
        )
        assert r["count"] == 2
        titles = [c["title"] for c in r["created"]]
        assert "A" in titles
        assert "B" in titles
        assert len(r["skipped_duplicates"]) == 1
        assert "A" in r["skipped_duplicates"][0]

    async def test_todo_batch_add_children_skips_existing(
        self,
        app: Any,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        p = await self._call(
            app,
            "todo_add",
            title="Parent",
            project_name="myapp",
        )
        await self._call(
            app,
            "todo_add",
            parent=p["todo_id"],
            title="X",
            project_name="myapp",
        )
        children = json.dumps([{"title": "X"}, {"title": "Y"}])
        r = await self._call(
            app,
            "todo_batch_add_children",
            parent_id=p["todo_id"],
            children=children,
            project_name="myapp",
        )
        assert r["count"] == 1
        assert r["created"][0]["title"] == "Y"
        assert len(r["skipped_duplicates"]) == 1
        assert "exists:" in r["skipped_duplicates"][0]
