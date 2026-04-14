"""Tests for hook deduplication — numeric hook-NNN removal when named hooks exist."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import yaml

from server.lib.models import Hook, HookRegistry
from server.lib.storage import load, save


class TestDeduplicateNumericHooks:
    """Test HookRegistry.deduplicate_numeric_hooks()."""

    def test_numeric_removed_when_named_exists(self):
        """hook-NNN removed when a named hook shares trigger+target+server."""
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
            ]
        )
        removed = registry.deduplicate_numeric_hooks()
        assert removed == ["hook-009"]
        assert len(registry.hooks) == 1
        assert registry.hooks[0].id == "proj-tracking-flush-on-todo-update"

    def test_both_named_survive(self):
        """Two named hooks with same trigger+target+server both survive."""
        registry = HookRegistry(
            hooks=[
                Hook(
                    id="plugin-a-hook",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                ),
                Hook(
                    id="plugin-b-hook",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                ),
            ]
        )
        removed = registry.deduplicate_numeric_hooks()
        assert removed == []
        assert len(registry.hooks) == 2

    def test_different_targets_survive(self):
        """Hooks with same trigger but different targets are not deduped."""
        registry = HookRegistry(
            hooks=[
                Hook(
                    id="hook-001",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                    source="auto",
                ),
                Hook(
                    id="named-hook",
                    trigger_tool="todo_update",
                    target_tool="todoist_update_tasks",
                    server="todoist",
                ),
            ]
        )
        removed = registry.deduplicate_numeric_hooks()
        assert removed == []
        assert len(registry.hooks) == 2

    def test_different_servers_survive(self):
        """Named hooks with same trigger+target but different servers both survive."""
        registry = HookRegistry(
            hooks=[
                Hook(
                    id="named-hook-a",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj-a",
                ),
                Hook(
                    id="named-hook-b",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj-b",
                ),
            ]
        )
        removed = registry.deduplicate_numeric_hooks()
        assert removed == []
        assert len(registry.hooks) == 2

    def test_only_numeric_hooks_survive(self):
        """When only numeric hooks exist (no named), all survive."""
        registry = HookRegistry(
            hooks=[
                Hook(
                    id="hook-001",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                    source="auto",
                ),
            ]
        )
        removed = registry.deduplicate_numeric_hooks()
        assert removed == []
        assert len(registry.hooks) == 1

    def test_multiple_numeric_duplicates_removed(self):
        """Multiple numeric hooks for same triplet are all removed."""
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
                    id="hook-099",
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
            ]
        )
        removed = registry.deduplicate_numeric_hooks()
        assert set(removed) == {"hook-009", "hook-099"}
        assert len(registry.hooks) == 1
        assert registry.hooks[0].id == "proj-tracking-flush-on-todo-update"


class TestIsNumericId:
    """Test Hook.is_numeric_id property."""

    def test_numeric_ids(self):
        h = Hook(id="hook-001", trigger_tool="t", target_tool="u", server="s")
        assert h.is_numeric_id is True
        h2 = Hook(id="hook-999", trigger_tool="t", target_tool="u", server="s")
        assert h2.is_numeric_id is True

    def test_named_ids(self):
        h = Hook(id="proj-tracking-flush", trigger_tool="t", target_tool="u", server="s")
        assert h.is_numeric_id is False
        h2 = Hook(id="todoist-on-todo-update", trigger_tool="t", target_tool="u", server="s")
        assert h2.is_numeric_id is False

    def test_hook_prefix_non_numeric(self):
        h = Hook(id="hook-abc", trigger_tool="t", target_tool="u", server="s")
        assert h.is_numeric_id is False


class TestDiscoveryDedup:
    """Test that discover_and_register replaces numeric hooks with named ones."""

    def test_discovery_replaces_numeric_with_named(self, tmp_path: Path):
        """When default-hooks.yaml has a named hook and registry has hook-NNN
        for the same triplet, discovery replaces the numeric one."""
        from server.lib.discovery import discover_and_register

        # Pre-existing registry with numeric hook
        registry = HookRegistry(
            hooks=[
                Hook(
                    id="hook-009",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                    param_mapping={"commit_message": "Todo: update ${todo_id}"},
                    blocking=True,
                    condition="git_tracking.enabled",
                    source="auto",
                ),
            ]
        )

        # Create plugin dir with default-hooks.yaml
        plugin_dir = tmp_path / "plugins" / "proj" / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        hooks_yaml = plugin_dir / "default-hooks.yaml"
        hooks_yaml.write_text(
            yaml.dump(
                {
                    "hooks": [
                        {
                            "id": "proj-tracking-flush-on-todo-update",
                            "trigger_tool": "todo_update",
                            "target_tool": "tracking_git_flush",
                            "server": "proj",
                            "param_mapping": {"commit_message": "Todo: update ${todo_id}"},
                            "blocking": True,
                            "condition": "git_tracking.enabled",
                        }
                    ]
                }
            )
        )

        stats = discover_and_register(registry, root=tmp_path)

        # Numeric hook should be gone, named should be present
        assert registry.find_by_id("hook-009") is None
        named = registry.find_by_id("proj-tracking-flush-on-todo-update")
        assert named is not None
        assert named.trigger_tool == "todo_update"
        assert named.target_tool == "tracking_git_flush"
        assert named.server == "proj"
        assert stats["proj"]["registered"] == 1

    def test_discovery_keeps_both_named(self, tmp_path: Path):
        """When registry has a named hook and default-hooks.yaml has the same
        named hook, discovery skips (no duplicate)."""
        from server.lib.discovery import discover_and_register

        registry = HookRegistry(
            hooks=[
                Hook(
                    id="proj-tracking-flush-on-todo-update",
                    trigger_tool="todo_update",
                    target_tool="tracking_git_flush",
                    server="proj",
                    blocking=True,
                    condition="git_tracking.enabled",
                ),
            ]
        )

        plugin_dir = tmp_path / "plugins" / "proj" / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        hooks_yaml = plugin_dir / "default-hooks.yaml"
        hooks_yaml.write_text(
            yaml.dump(
                {
                    "hooks": [
                        {
                            "id": "proj-tracking-flush-on-todo-update",
                            "trigger_tool": "todo_update",
                            "target_tool": "tracking_git_flush",
                            "server": "proj",
                            "blocking": True,
                            "condition": "git_tracking.enabled",
                        }
                    ]
                }
            )
        )

        stats = discover_and_register(registry, root=tmp_path)

        # Should not register new, existing named hook survives
        assert len(registry.hooks) == 1
        assert registry.hooks[0].id == "proj-tracking-flush-on-todo-update"
        assert stats["proj"]["registered"] == 0


class TestRunDiscoveryDedup:
    """Test that run_discovery cleans up existing numeric duplicates at startup."""

    def test_startup_cleanup(self, tmp_path: Path):
        """run_discovery removes pre-existing numeric duplicates on startup."""
        from server.lib.discovery import run_discovery

        hooks_file = tmp_path / "hooks.yaml"

        # Registry with both numeric + named for same triplet
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
            ]
        )
        save(registry, hooks_file)

        with patch("server.lib.storage._HOOKS_FILE", hooks_file):
            summary = run_discovery(root=tmp_path)

        assert "hook-009" in summary
        assert "Deduplicated" in summary

        # Verify on disk
        reloaded = load(hooks_file)
        assert reloaded.find_by_id("hook-009") is None
        assert reloaded.find_by_id("proj-tracking-flush-on-todo-update") is not None
