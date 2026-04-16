"""Tests for HookRegistry.deduplicate_by_hook_id() — collapse same-id duplicates."""

from __future__ import annotations

from server.lib.models import Hook, HookRegistry


class TestDeduplicateByHookId:
    """Test HookRegistry.deduplicate_by_hook_id()."""

    def test_same_id_collapses_to_one(self):
        """Two entries sharing a hook.id collapse to a single hook."""
        registry = HookRegistry(
            hooks=[
                Hook(
                    id="proj-tracking-flush-on-todo-update",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                ),
                Hook(
                    id="proj-tracking-flush-on-todo-update",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                ),
            ]
        )
        removed = registry.deduplicate_by_hook_id()
        assert removed == ["proj-tracking-flush-on-todo-update"]
        assert len(registry.hooks) == 1

    def test_canonical_server_wins_over_blank(self):
        """When one dup has a canonical server and the other has an off-registry
        server, the canonical entry is kept regardless of list order."""
        registry = HookRegistry(
            hooks=[
                Hook(
                    id="x-hook",
                    trigger_tool="t",
                    target_tool="u",
                    server="proj",  # canonical (in DEFAULT_SERVER_PORTS)
                ),
                Hook(
                    id="x-hook",
                    trigger_tool="t",
                    target_tool="u",
                    server="wrong-server",  # not in DEFAULT_SERVER_PORTS
                ),
            ]
        )
        removed = registry.deduplicate_by_hook_id()
        assert removed == ["x-hook"]
        assert len(registry.hooks) == 1
        assert registry.hooks[0].server == "proj"

    def test_list_position_tiebreak_when_all_canonical(self):
        """Two canonical entries: last in list wins (freshest wins)."""
        registry = HookRegistry(
            hooks=[
                Hook(id="y-hook", trigger_tool="t", target_tool="u", server="proj"),
                Hook(id="y-hook", trigger_tool="t", target_tool="u", server="todoist"),
            ]
        )
        removed = registry.deduplicate_by_hook_id()
        assert removed == ["y-hook"]
        assert registry.hooks[0].server == "todoist"

    def test_three_way_duplicate_returns_two_removed(self):
        """Three entries → one survivor, two removed ids (id appears twice)."""
        registry = HookRegistry(
            hooks=[
                Hook(id="z-hook", trigger_tool="t", target_tool="u", server="proj"),
                Hook(id="z-hook", trigger_tool="t", target_tool="u", server="proj"),
                Hook(id="z-hook", trigger_tool="t", target_tool="u", server="proj"),
            ]
        )
        removed = registry.deduplicate_by_hook_id()
        assert removed == ["z-hook", "z-hook"]
        assert len(registry.hooks) == 1

    def test_no_duplicates_is_noop(self):
        """Registry with unique hook ids is unchanged; returns empty list."""
        registry = HookRegistry(
            hooks=[
                Hook(id="a-hook", trigger_tool="t", target_tool="u", server="proj"),
                Hook(id="b-hook", trigger_tool="t", target_tool="v", server="proj"),
            ]
        )
        before = list(registry.hooks)
        removed = registry.deduplicate_by_hook_id()
        assert removed == []
        assert registry.hooks == before

    def test_composes_with_numeric_dedup(self):
        """deduplicate_numeric_hooks then deduplicate_by_hook_id leave a clean registry."""
        registry = HookRegistry(
            hooks=[
                Hook(
                    id="hook-009",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                    source="auto",
                ),
                Hook(
                    id="proj-tracking-flush-on-todo-update",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                ),
                Hook(
                    id="proj-tracking-flush-on-todo-update",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                ),
            ]
        )
        numeric_removed = registry.deduplicate_numeric_hooks()
        id_removed = registry.deduplicate_by_hook_id()
        assert numeric_removed == ["hook-009"]
        assert id_removed == ["proj-tracking-flush-on-todo-update"]
        assert len(registry.hooks) == 1
        assert registry.hooks[0].id == "proj-tracking-flush-on-todo-update"
