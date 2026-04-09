"""Tests for todo_analyze_graph MCP tool."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from server.lib import storage
from server.lib.ids import next_todo_id
from server.lib.models import ProjConfig, ProjectMeta, Todo
from tests.conftest import call_tool, setup_project


def _make_todo(meta: ProjectMeta, title: str, **kwargs: object) -> Todo:
    today = str(date.today())
    todo = Todo(id=next_todo_id(meta), title=title, created=today, updated=today)
    for k, v in kwargs.items():
        setattr(todo, k, v)
    return todo


@pytest.fixture()
def project(cfg: ProjConfig, tmp_path: Path) -> tuple[ProjConfig, str, ProjectMeta]:
    """Create a project named 'myapp' and return (cfg, name, meta)."""
    name = "myapp"
    setup_project(cfg, name, str(tmp_path / "repo"))
    meta = storage.load_meta(cfg, name)
    return cfg, name, meta


async def _analyze(app: Any, name: str = "myapp") -> dict[str, Any]:
    """Call todo_analyze_graph and parse the JSON result."""
    raw = await call_tool(app, "todo_analyze_graph", project_name=name)
    return json.loads(raw)


@pytest.mark.asyncio
class TestAnalyzeGraph:
    async def test_empty_project(
        self, mcp_app: Any, project: tuple[ProjConfig, str, ProjectMeta]
    ) -> None:
        """Empty project — 0 active todos, empty tiers and lists."""
        data = await _analyze(mcp_app)
        assert data["todos"] == []
        assert data["tiers"] == []
        assert data["cycles"] == []
        assert data["critical_path"] == []
        assert data["orphans"] == []

    async def test_single_todo(
        self, mcp_app: Any, project: tuple[ProjConfig, str, ProjectMeta]
    ) -> None:
        """Single todo — 1 tier, orphan, depth=0, fan_out=0."""
        cfg, name, meta = project
        t1 = _make_todo(meta, "Only task")
        storage.save_todos(cfg, name, [t1])

        data = await _analyze(mcp_app)
        assert len(data["todos"]) == 1
        assert data["tiers"] == [[t1.id]]
        assert data["orphans"] == [t1.id]
        assert data["todos"][0]["critical_path_depth"] == 0
        assert data["todos"][0]["transitive_fan_out"] == 0

    async def test_linear_chain(
        self, mcp_app: Any, project: tuple[ProjConfig, str, ProjectMeta]
    ) -> None:
        """Linear chain A→B→C — 3 tiers, critical_path=[A,B,C], depth A=2, B=1, C=0."""
        cfg, name, meta = project
        a = _make_todo(meta, "A")
        b = _make_todo(meta, "B", blocked_by=[a.id])
        c = _make_todo(meta, "C", blocked_by=[b.id])
        a.blocks.append(b.id)
        b.blocks.append(c.id)
        storage.save_todos(cfg, name, [a, b, c])

        data = await _analyze(mcp_app)
        assert len(data["tiers"]) == 3
        assert data["critical_path"] == [a.id, b.id, c.id]

        by_id = {t["id"]: t for t in data["todos"]}
        assert by_id[a.id]["critical_path_depth"] == 2
        assert by_id[b.id]["critical_path_depth"] == 1
        assert by_id[c.id]["critical_path_depth"] == 0

    async def test_diamond(
        self, mcp_app: Any, project: tuple[ProjConfig, str, ProjectMeta]
    ) -> None:
        """Diamond A→B, A→C, B→D, C→D — 3 tiers, fan_out(A)=3."""
        cfg, name, meta = project
        a = _make_todo(meta, "A")
        b = _make_todo(meta, "B", blocked_by=[a.id])
        c = _make_todo(meta, "C", blocked_by=[a.id])
        d = _make_todo(meta, "D", blocked_by=[b.id, c.id])
        a.blocks.extend([b.id, c.id])
        b.blocks.append(d.id)
        c.blocks.append(d.id)
        storage.save_todos(cfg, name, [a, b, c, d])

        data = await _analyze(mcp_app)
        assert len(data["tiers"]) == 3

        by_id = {t["id"]: t for t in data["todos"]}
        # A has 3 downstream: B, C, D
        assert by_id[a.id]["transitive_fan_out"] == 3

    async def test_forest_two_independent_chains(
        self, mcp_app: Any, project: tuple[ProjConfig, str, ProjectMeta]
    ) -> None:
        """Forest — two independent chains, both roots in tier 0."""
        cfg, name, meta = project
        a = _make_todo(meta, "A")
        b = _make_todo(meta, "B", blocked_by=[a.id])
        a.blocks.append(b.id)
        c = _make_todo(meta, "C")
        d = _make_todo(meta, "D", blocked_by=[c.id])
        c.blocks.append(d.id)
        storage.save_todos(cfg, name, [a, b, c, d])

        data = await _analyze(mcp_app)
        # Tier 0 contains both roots
        assert a.id in data["tiers"][0]
        assert c.id in data["tiers"][0]

    async def test_cycle_detection(
        self, mcp_app: Any, project: tuple[ProjConfig, str, ProjectMeta]
    ) -> None:
        """Cycle — A blocks B, B blocks A → cycles detected, depth/fan_out = -1."""
        cfg, name, meta = project
        a = _make_todo(meta, "A", blocked_by=["2"])
        b = _make_todo(meta, "B", blocked_by=[a.id])
        a.blocks.append(b.id)
        b.blocks.append(a.id)
        storage.save_todos(cfg, name, [a, b])

        result = await _analyze(mcp_app)
        assert len(result["cycles"]) > 0
        # Cycle nodes get indeterminate metrics
        for todo in result["todos"]:
            assert todo["critical_path_depth"] == -1
            assert todo["transitive_fan_out"] == -1

    async def test_mixed_done_active(
        self, mcp_app: Any, project: tuple[ProjConfig, str, ProjectMeta]
    ) -> None:
        """Create 3 todos, mark 1 done — only 2 in output."""
        cfg, name, meta = project
        t1 = _make_todo(meta, "Active 1")
        t2 = _make_todo(meta, "Done task", status="done")
        t3 = _make_todo(meta, "Active 2")
        storage.save_todos(cfg, name, [t1, t2, t3])

        data = await _analyze(mcp_app)
        assert len(data["todos"]) == 2
        ids = {t["id"] for t in data["todos"]}
        assert t2.id not in ids

    async def test_orphans(
        self, mcp_app: Any, project: tuple[ProjConfig, str, ProjectMeta]
    ) -> None:
        """Todo with no blocking edges appears in orphans list."""
        cfg, name, meta = project
        orphan = _make_todo(meta, "Orphan")
        a = _make_todo(meta, "A")
        b = _make_todo(meta, "B", blocked_by=[a.id])
        a.blocks.append(b.id)
        storage.save_todos(cfg, name, [orphan, a, b])

        data = await _analyze(mcp_app)
        assert orphan.id in data["orphans"]
        # A and B are connected, not orphans
        assert a.id not in data["orphans"]
        assert b.id not in data["orphans"]

    async def test_is_on_critical_path_flag(
        self, mcp_app: Any, project: tuple[ProjConfig, str, ProjectMeta]
    ) -> None:
        """is_on_critical_path flag matches the critical_path list."""
        cfg, name, meta = project
        a = _make_todo(meta, "A")
        b = _make_todo(meta, "B", blocked_by=[a.id])
        a.blocks.append(b.id)
        orphan = _make_todo(meta, "Orphan")
        storage.save_todos(cfg, name, [a, b, orphan])

        data = await _analyze(mcp_app)
        cp_set = set(data["critical_path"])
        for todo in data["todos"]:
            if todo["id"] in cp_set:
                assert todo["is_on_critical_path"] is True
            else:
                assert todo["is_on_critical_path"] is False

    async def test_fan_out_accuracy(
        self, mcp_app: Any, project: tuple[ProjConfig, str, ProjectMeta]
    ) -> None:
        """Transitive fan-out counts all downstream deps accurately."""
        cfg, name, meta = project
        # A → B → D
        # A → C → D
        # So A has fan_out=3 (B, C, D), B has fan_out=1 (D), C has fan_out=1 (D), D has 0
        a = _make_todo(meta, "A")
        b = _make_todo(meta, "B", blocked_by=[a.id])
        c = _make_todo(meta, "C", blocked_by=[a.id])
        d = _make_todo(meta, "D", blocked_by=[b.id, c.id])
        a.blocks.extend([b.id, c.id])
        b.blocks.append(d.id)
        c.blocks.append(d.id)
        storage.save_todos(cfg, name, [a, b, c, d])

        data = await _analyze(mcp_app)
        by_id = {t["id"]: t for t in data["todos"]}
        assert by_id[a.id]["transitive_fan_out"] == 3
        assert by_id[b.id]["transitive_fan_out"] == 1
        assert by_id[c.id]["transitive_fan_out"] == 1
        assert by_id[d.id]["transitive_fan_out"] == 0
