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
