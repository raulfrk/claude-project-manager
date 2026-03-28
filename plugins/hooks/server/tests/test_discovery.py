"""Tests for server.lib.discovery — auto-discover default-hooks.yaml from sibling plugins."""

from __future__ import annotations

from pathlib import Path

import yaml

from server.lib.discovery import (
    _DEFAULT_SERVER_PORTS,
    discover_and_register,
    find_default_hooks_files,
    load_hooks_from_file,
    populate_server_urls,
)
from server.lib.models import HookRegistry


def _setup_plugin(
    root: Path,
    plugin_name: str,
    hooks: list[dict] | None = None,
    *,
    raw_content: str | None = None,
) -> Path:
    """Create a plugin directory structure with optional default-hooks.yaml."""
    plugin_dir = root / "plugins" / plugin_name / ".claude-plugin"
    plugin_dir.mkdir(parents=True, exist_ok=True)
    hooks_file = plugin_dir / "default-hooks.yaml"
    if raw_content is not None:
        hooks_file.write_text(raw_content)
    elif hooks is not None:
        hooks_file.write_text(yaml.dump({"hooks": hooks}, default_flow_style=False))
    return hooks_file


# ── find_default_hooks_files ─────────────────────────────────────────────────


class TestFindDefaultHooksFiles:
    def test_no_plugins(self, tmp_path: Path):
        (tmp_path / "plugins").mkdir()
        assert find_default_hooks_files(root=tmp_path) == []

    def test_plugin_without_hooks_file(self, tmp_path: Path):
        plugin_dir = tmp_path / "plugins" / "perms" / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        assert find_default_hooks_files(root=tmp_path) == []

    def test_finds_hooks_files(self, tmp_path: Path):
        _setup_plugin(tmp_path, "perms", hooks=[])
        _setup_plugin(tmp_path, "proj", hooks=[])
        found = find_default_hooks_files(root=tmp_path)
        assert len(found) == 2
        names = {p.parent.parent.name for p in found}
        assert names == {"perms", "proj"}

    def test_only_finds_in_claude_plugin_dir(self, tmp_path: Path):
        """Files outside .claude-plugin/ are not found."""
        plugin_dir = tmp_path / "plugins" / "perms"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "default-hooks.yaml").write_text("hooks: []")
        assert find_default_hooks_files(root=tmp_path) == []


# ── load_hooks_from_file ────────────────────────────────────────────────────


class TestLoadHooksFromFile:
    def test_valid_file(self, tmp_path: Path):
        path = _setup_plugin(tmp_path, "perms", hooks=[
            {"trigger_tool": "proj_init", "target_tool": "perms_setup", "server": "perms"},
        ])
        result = load_hooks_from_file(path)
        assert len(result) == 1
        assert result[0]["trigger_tool"] == "proj_init"

    def test_empty_hooks_list(self, tmp_path: Path):
        path = _setup_plugin(tmp_path, "perms", hooks=[])
        assert load_hooks_from_file(path) == []

    def test_missing_file(self, tmp_path: Path):
        assert load_hooks_from_file(tmp_path / "nope.yaml") == []

    def test_invalid_yaml(self, tmp_path: Path):
        path = _setup_plugin(tmp_path, "perms", raw_content=": invalid: {{{")
        result = load_hooks_from_file(path)
        assert result == []

    def test_non_dict_top_level(self, tmp_path: Path):
        path = _setup_plugin(tmp_path, "perms", raw_content="- item1\n- item2\n")
        assert load_hooks_from_file(path) == []

    def test_non_list_hooks_key(self, tmp_path: Path):
        path = _setup_plugin(tmp_path, "perms", raw_content="hooks: not-a-list\n")
        assert load_hooks_from_file(path) == []

    def test_skips_non_dict_entries(self, tmp_path: Path):
        path = _setup_plugin(
            tmp_path,
            "perms",
            raw_content=yaml.dump({
                "hooks": [
                    {"trigger_tool": "a", "target_tool": "b", "server": "s"},
                    "not-a-dict",
                    42,
                ],
            }),
        )
        result = load_hooks_from_file(path)
        assert len(result) == 1

    def test_multiple_hooks(self, tmp_path: Path):
        path = _setup_plugin(tmp_path, "perms", hooks=[
            {"trigger_tool": "a", "target_tool": "b", "server": "s1"},
            {"trigger_tool": "c", "target_tool": "d", "server": "s2"},
        ])
        assert len(load_hooks_from_file(path)) == 2

    def test_preserves_verification_field(self, tmp_path: Path):
        """The verification field in YAML entries is preserved in the raw dict."""
        path = _setup_plugin(tmp_path, "todoist", hooks=[
            {
                "trigger_tool": "todo_complete",
                "target_tool": "todoist_verify",
                "server": "todoist",
                "verification": True,
            },
        ])
        result = load_hooks_from_file(path)
        assert len(result) == 1
        assert result[0]["verification"] is True


# ── discover_and_register ───────────────────────────────────────────────────


class TestDiscoverAndRegister:
    def test_no_plugins_no_changes(self, tmp_path: Path):
        (tmp_path / "plugins").mkdir()
        registry = HookRegistry()
        stats = discover_and_register(registry, root=tmp_path)
        assert stats == {}
        assert registry.hooks == []

    def test_registers_hooks_from_plugin(self, tmp_path: Path):
        _setup_plugin(tmp_path, "perms", hooks=[
            {"trigger_tool": "proj_init", "target_tool": "perms_setup", "server": "perms"},
        ])
        registry = HookRegistry()
        stats = discover_and_register(registry, root=tmp_path)
        assert stats == {"perms": 1}
        assert len(registry.hooks) == 1
        assert registry.hooks[0].source == "auto"
        assert registry.hooks[0].trigger_tool == "proj_init"

    def test_idempotent_registration(self, tmp_path: Path):
        _setup_plugin(tmp_path, "perms", hooks=[
            {"trigger_tool": "proj_init", "target_tool": "perms_setup", "server": "perms"},
        ])
        registry = HookRegistry()
        discover_and_register(registry, root=tmp_path)
        assert len(registry.hooks) == 1

        # Run again — should not add duplicates
        stats2 = discover_and_register(registry, root=tmp_path)
        assert stats2 == {"perms": 0}
        assert len(registry.hooks) == 1

    def test_skips_hooks_missing_required_fields(self, tmp_path: Path):
        _setup_plugin(tmp_path, "perms", hooks=[
            {"trigger_tool": "a"},  # missing target_tool and server
            {"trigger_tool": "a", "target_tool": "b", "server": "s"},
        ])
        registry = HookRegistry()
        stats = discover_and_register(registry, root=tmp_path)
        assert stats == {"perms": 1}
        assert len(registry.hooks) == 1

    def test_multiple_plugins(self, tmp_path: Path):
        _setup_plugin(tmp_path, "perms", hooks=[
            {"trigger_tool": "a", "target_tool": "b", "server": "perms"},
        ])
        _setup_plugin(tmp_path, "proj", hooks=[
            {"trigger_tool": "c", "target_tool": "d", "server": "proj"},
        ])
        registry = HookRegistry()
        stats = discover_and_register(registry, root=tmp_path)
        assert stats == {"perms": 1, "proj": 1}
        assert len(registry.hooks) == 2

    def test_assigns_incremental_ids(self, tmp_path: Path):
        _setup_plugin(tmp_path, "perms", hooks=[
            {"trigger_tool": "a", "target_tool": "b", "server": "s"},
            {"trigger_tool": "c", "target_tool": "d", "server": "s"},
        ])
        registry = HookRegistry()
        discover_and_register(registry, root=tmp_path)
        ids = [h.id for h in registry.hooks]
        assert ids == ["hook-001", "hook-002"]

    def test_tracks_server_endpoints(self, tmp_path: Path):
        _setup_plugin(tmp_path, "perms", hooks=[
            {"trigger_tool": "a", "target_tool": "b", "server": "new-server"},
        ])
        registry = HookRegistry()
        discover_and_register(registry, root=tmp_path)
        assert "new-server" in registry.servers

    def test_preserves_existing_hooks(self, tmp_path: Path):
        """Existing manually-registered hooks are not affected."""
        from server.lib.models import Hook

        existing = Hook(
            id="hook-001",
            trigger_tool="manual",
            target_tool="manual_target",
            server="manual_server",
        )
        registry = HookRegistry(hooks=[existing])

        _setup_plugin(tmp_path, "perms", hooks=[
            {"trigger_tool": "a", "target_tool": "b", "server": "s"},
        ])
        discover_and_register(registry, root=tmp_path)
        assert len(registry.hooks) == 2
        assert registry.hooks[0].id == "hook-001"
        assert registry.hooks[1].id == "hook-002"

    def test_registers_verification_hook(self, tmp_path: Path):
        """Hooks with verification: true are registered with verification=True and blocking forced."""
        _setup_plugin(tmp_path, "todoist", hooks=[
            {
                "trigger_tool": "todo_complete",
                "target_tool": "todoist_verify_complete",
                "server": "todoist",
                "param_mapping": {"todoist_task_id": "${result.todoist_task_id}"},
                "verification": True,
                "condition": "todoist.enabled and todoist.auto_sync",
            },
        ])
        registry = HookRegistry()
        stats = discover_and_register(registry, root=tmp_path)
        assert stats == {"todoist": 1}
        assert len(registry.hooks) == 1
        hook = registry.hooks[0]
        assert hook.verification is True
        assert hook.blocking is True  # forced by verification
        assert hook.condition == "todoist.enabled and todoist.auto_sync"
        assert hook.source == "auto"

    def test_verification_false_by_default(self, tmp_path: Path):
        """Hooks without explicit verification field default to verification=False."""
        _setup_plugin(tmp_path, "perms", hooks=[
            {"trigger_tool": "proj_init", "target_tool": "perms_setup", "server": "perms"},
        ])
        registry = HookRegistry()
        discover_and_register(registry, root=tmp_path)
        assert registry.hooks[0].verification is False

    def test_mixed_primary_and_verification_hooks(self, tmp_path: Path):
        """Plugin with both primary and verification hooks registers both correctly."""
        _setup_plugin(tmp_path, "todoist", hooks=[
            {
                "trigger_tool": "todo_complete",
                "target_tool": "todoist_sync",
                "server": "todoist",
                "blocking": True,
            },
            {
                "trigger_tool": "todo_complete",
                "target_tool": "todoist_verify_complete",
                "server": "todoist",
                "verification": True,
            },
        ])
        registry = HookRegistry()
        stats = discover_and_register(registry, root=tmp_path)
        assert stats == {"todoist": 2}
        assert len(registry.hooks) == 2

        primary = [h for h in registry.hooks if not h.verification]
        verification = [h for h in registry.hooks if h.verification]
        assert len(primary) == 1
        assert len(verification) == 1
        assert verification[0].blocking is True
        assert primary[0].target_tool == "todoist_sync"
        assert verification[0].target_tool == "todoist_verify_complete"


# ── populate_server_urls ─────────────────────────────────────────────────────


class TestPopulateServerUrls:
    def test_populate_server_urls_adds_all_defaults(self):
        registry = HookRegistry()
        added = populate_server_urls(registry)
        assert added == len(_DEFAULT_SERVER_PORTS)
        for name, port in _DEFAULT_SERVER_PORTS.items():
            assert registry.servers[name]["url"] == f"http://127.0.0.1:{port}/hook"

    def test_populate_server_urls_preserves_manual_override(self):
        registry = HookRegistry(servers={"perms": {"url": "http://custom:9999/hook"}})
        added = populate_server_urls(registry)
        assert registry.servers["perms"]["url"] == "http://custom:9999/hook"
        assert added == len(_DEFAULT_SERVER_PORTS) - 1

    def test_populate_server_urls_with_port_override(self):
        registry = HookRegistry()
        added = populate_server_urls(registry, port_overrides={"perms": 29101})
        assert registry.servers["perms"]["url"] == "http://127.0.0.1:29101/hook"
        assert added == len(_DEFAULT_SERVER_PORTS)

    def test_populate_server_urls_idempotent(self):
        registry = HookRegistry()
        first = populate_server_urls(registry)
        assert first == len(_DEFAULT_SERVER_PORTS)
        second = populate_server_urls(registry)
        assert second == 0
        # No duplicates — same count of servers
        assert len(registry.servers) == len(_DEFAULT_SERVER_PORTS)
