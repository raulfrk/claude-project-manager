"""Tests for --prio tier computation logic via proj_identify_batches.

Validates the topological sort / Kahn's algorithm used by the --prio skill
flag: filtering active todos, removing stale blockers, and computing tiers.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from server.lib import state, storage
from server.lib.models import ProjConfig
from tests.conftest import call_tool, setup_project


@pytest.fixture()
def project(cfg: ProjConfig, tmp_path: Any) -> tuple[ProjConfig, str]:
    setup_project(cfg, "myapp", str(tmp_path))
    state.set_session_active("myapp")
    return cfg, "myapp"


def _parse(result: str) -> dict[str, Any]:
    return json.loads(result)


@pytest.mark.asyncio
class TestPrioTiers:
    """Tier computation scenarios that the --prio skill flag relies on."""

    async def test_all_independent_single_batch(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """All independent todos (no blocking edges) -> single batch containing all."""
        await call_tool(mcp_app, "todo_add", title="Alpha")
        await call_tool(mcp_app, "todo_add", title="Beta")
        await call_tool(mcp_app, "todo_add", title="Gamma")

        result = await call_tool(mcp_app, "proj_identify_batches", todo_ids=["1", "2", "3"])
        data = _parse(result)

        assert len(data["batches"]) == 1
        assert set(data["batches"][0]) == {"1", "2", "3"}
        assert data["cycles"] == []
        assert data["missing"] == []

    async def test_linear_chain_three_batches(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Linear chain A blocks B blocks C -> 3 batches."""
        await call_tool(mcp_app, "todo_add", title="A")
        await call_tool(mcp_app, "todo_add", title="B")
        await call_tool(mcp_app, "todo_add", title="C")
        # Set up chain: 1 blocks 2, 2 blocks 3
        await call_tool(mcp_app, "todo_block", todo_id="1", blocks_ids=["2"])
        await call_tool(mcp_app, "todo_block", todo_id="2", blocks_ids=["3"])

        result = await call_tool(mcp_app, "proj_identify_batches", todo_ids=["1", "2", "3"])
        data = _parse(result)

        assert data["batches"] == [["1"], ["2"], ["3"]]
        assert data["order"] == ["1", "2", "3"]
        assert data["cycles"] == []

    async def test_stale_blocker_done_excluded(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Stale blockers: A blocks B, A is done. Skill passes only active [B] -> B in tier 0."""
        await call_tool(mcp_app, "todo_add", title="A")
        await call_tool(mcp_app, "todo_add", title="B")
        await call_tool(mcp_app, "todo_block", todo_id="1", blocks_ids=["2"])
        # Mark A as done
        await call_tool(mcp_app, "todo_complete", todo_id="1")

        # The skill filters out done todos before calling identify_batches,
        # so we only pass the active todo IDs.
        result = await call_tool(mcp_app, "proj_identify_batches", todo_ids=["2"])
        data = _parse(result)

        # B's blocker (1) is not in the requested set, so B has no active blockers
        assert data["batches"] == [["2"]]
        assert data["cycles"] == []

    async def test_deleted_blocker_appears_in_missing(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Deleted blockers: B has blocked_by=[nonexistent],
        call with [B] -> B tier 0, nonexistent in missing."""
        await call_tool(mcp_app, "todo_add", title="B", blocked_by=["999"])

        result = await call_tool(mcp_app, "proj_identify_batches", todo_ids=["1", "999"])
        data = _parse(result)

        assert "999" in data["missing"]
        # B (id=1) is in tier 0 since its blocker 999 is not in the requested set
        assert data["batches"] == [["1"]]
        assert data["cycles"] == []

    async def test_circular_dependency_detected(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Circular dependency: A blocks B, B blocks A -> cycles detected."""
        await call_tool(mcp_app, "todo_add", title="A", blocked_by=["2"])
        await call_tool(mcp_app, "todo_add", title="B", blocked_by=["1"])

        result = await call_tool(mcp_app, "proj_identify_batches", todo_ids=["1", "2"])
        data = _parse(result)

        assert len(data["cycles"]) > 0
        # Both nodes should appear in cycle descriptions
        cycle_text = " ".join(data["cycles"])
        assert "1" in cycle_text
        assert "2" in cycle_text
        # No batches should contain cycle nodes
        all_batched = {tid for batch in data["batches"] for tid in batch}
        assert "1" not in all_batched
        assert "2" not in all_batched

    async def test_diamond_dependency_tiers(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Diamond: A blocks B and C, both B and C block D.

        Expected tiers:
          tier 0: [A]
          tier 1: [B, C]
          tier 2: [D]
        """
        await call_tool(mcp_app, "todo_add", title="A")  # 1
        await call_tool(mcp_app, "todo_add", title="B")  # 2
        await call_tool(mcp_app, "todo_add", title="C")  # 3
        await call_tool(mcp_app, "todo_add", title="D")  # 4
        await call_tool(mcp_app, "todo_block", todo_id="1", blocks_ids=["2", "3"])
        await call_tool(mcp_app, "todo_block", todo_id="2", blocks_ids=["4"])
        await call_tool(mcp_app, "todo_block", todo_id="3", blocks_ids=["4"])

        result = await call_tool(mcp_app, "proj_identify_batches", todo_ids=["1", "2", "3", "4"])
        data = _parse(result)

        assert data["batches"][0] == ["1"]
        assert set(data["batches"][1]) == {"2", "3"}
        assert data["batches"][2] == ["4"]
        assert len(data["batches"]) == 3
        assert data["cycles"] == []

    async def test_mixed_priorities_sortable_within_tier(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """Mixed priorities within a tier: verify data allows high->medium->low sorting.

        The skill sorts each batch by priority (high > medium > low), then by ID.
        identify_batches itself sorts by ID; verify the todos carry correct
        priority data so the skill can re-sort.
        """
        await call_tool(mcp_app, "todo_add", title="Low task", priority="low")  # 1
        await call_tool(mcp_app, "todo_add", title="High task", priority="high")  # 2
        await call_tool(mcp_app, "todo_add", title="Medium task", priority="medium")  # 3
        await call_tool(mcp_app, "todo_add", title="High task 2", priority="high")  # 4

        result = await call_tool(mcp_app, "proj_identify_batches", todo_ids=["1", "2", "3", "4"])
        data = _parse(result)

        # All independent -> single batch
        assert len(data["batches"]) == 1
        assert set(data["batches"][0]) == {"1", "2", "3", "4"}

        # Verify todos carry correct priorities for skill-level sorting
        cfg, name = project
        todos = storage.load_todos(cfg, name)
        todo_map = {t.id: t for t in todos}

        priority_order = {"high": 0, "medium": 1, "low": 2}
        batch_ids = data["batches"][0]
        # Simulate skill sorting: by priority then by ID
        sorted_ids = sorted(
            batch_ids,
            key=lambda tid: (priority_order.get(todo_map[tid].priority, 1), tid),
        )
        assert sorted_ids == ["2", "4", "3", "1"]

    async def test_partial_chain_with_external_blocker(
        self, mcp_app: Any, project: tuple[ProjConfig, str]
    ) -> None:
        """When a blocker is not in the requested set, it is ignored for tier computation."""
        await call_tool(mcp_app, "todo_add", title="A")  # 1
        await call_tool(mcp_app, "todo_add", title="B")  # 2
        await call_tool(mcp_app, "todo_add", title="C")  # 3
        await call_tool(mcp_app, "todo_block", todo_id="1", blocks_ids=["2"])
        await call_tool(mcp_app, "todo_block", todo_id="2", blocks_ids=["3"])

        # Only request B and C (A is external to the requested set)
        result = await call_tool(mcp_app, "proj_identify_batches", todo_ids=["2", "3"])
        data = _parse(result)

        # B's blocker (1) is not in requested set, so B is tier 0
        # C depends on B, so C is tier 1
        assert data["batches"] == [["2"], ["3"]]
        assert data["cycles"] == []
