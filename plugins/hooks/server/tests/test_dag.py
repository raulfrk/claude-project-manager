"""Tests for server.lib.dag — cycle detection in the hook dependency graph."""

from __future__ import annotations

from server.lib.dag import find_cycle_path, would_create_cycle
from server.lib.models import Hook


def _hook(trigger: str, target: str) -> Hook:
    """Shorthand to create a Hook for graph testing."""
    return Hook(
        id=f"hook-{trigger}-{target}",
        trigger_tool=trigger,
        target_tool=target,
        server="s",
    )


# ── would_create_cycle ───────────────────────────────────────────────────────


class TestWouldCreateCycle:
    def test_self_reference(self):
        assert would_create_cycle([], "A", "A") is True

    def test_no_hooks_no_cycle(self):
        assert would_create_cycle([], "A", "B") is False

    def test_direct_reverse_creates_cycle(self):
        """A -> B exists; adding B -> A would create A -> B -> A."""
        hooks = [_hook("A", "B")]
        assert would_create_cycle(hooks, "B", "A") is True

    def test_transitive_cycle(self):
        """A -> B -> C exists; adding C -> A would create cycle."""
        hooks = [_hook("A", "B"), _hook("B", "C")]
        assert would_create_cycle(hooks, "C", "A") is True

    def test_no_transitive_cycle(self):
        """A -> B -> C exists; adding A -> C is fine (no cycle)."""
        hooks = [_hook("A", "B"), _hook("B", "C")]
        assert would_create_cycle(hooks, "A", "C") is False

    def test_parallel_edges_no_cycle(self):
        """A -> B, A -> C; adding D -> A is fine."""
        hooks = [_hook("A", "B"), _hook("A", "C")]
        assert would_create_cycle(hooks, "D", "A") is False

    def test_diamond_no_cycle(self):
        """A -> B, A -> C, B -> D, C -> D; adding E -> A is fine."""
        hooks = [_hook("A", "B"), _hook("A", "C"), _hook("B", "D"), _hook("C", "D")]
        assert would_create_cycle(hooks, "E", "A") is False

    def test_diamond_with_cycle(self):
        """A -> B, A -> C, B -> D, C -> D; adding D -> A would cycle."""
        hooks = [_hook("A", "B"), _hook("A", "C"), _hook("B", "D"), _hook("C", "D")]
        assert would_create_cycle(hooks, "D", "A") is True

    def test_long_chain(self):
        """Chain of 10 nodes; closing the loop detects cycle."""
        hooks = [_hook(f"n{i}", f"n{i+1}") for i in range(10)]
        assert would_create_cycle(hooks, "n10", "n0") is True
        assert would_create_cycle(hooks, "n10", "n5") is True
        assert would_create_cycle(hooks, "n5", "n10") is False

    def test_disjoint_graphs_no_cycle(self):
        """Two separate chains; connecting them forward is safe."""
        hooks = [_hook("A", "B"), _hook("C", "D")]
        assert would_create_cycle(hooks, "B", "C") is False

    def test_empty_hooks_new_nodes(self):
        """Brand new nodes with no existing graph."""
        assert would_create_cycle([], "X", "Y") is False


# ── find_cycle_path ──────────────────────────────────────────────────────────


class TestFindCyclePath:
    def test_self_reference_path(self):
        path = find_cycle_path([], "A", "A")
        assert path == ["A", "A"]

    def test_no_cycle_returns_none(self):
        assert find_cycle_path([], "A", "B") is None

    def test_direct_cycle_path(self):
        hooks = [_hook("A", "B")]
        path = find_cycle_path(hooks, "B", "A")
        assert path is not None
        # Path should start and end with the same node
        assert path[0] == path[-1]
        assert "A" in path
        assert "B" in path

    def test_transitive_cycle_path(self):
        hooks = [_hook("A", "B"), _hook("B", "C")]
        path = find_cycle_path(hooks, "C", "A")
        assert path is not None
        assert path[0] == path[-1]
        # All three nodes should appear
        assert "A" in path
        assert "B" in path
        assert "C" in path

    def test_no_cycle_path_returns_none(self):
        hooks = [_hook("A", "B"), _hook("B", "C")]
        assert find_cycle_path(hooks, "A", "C") is None
