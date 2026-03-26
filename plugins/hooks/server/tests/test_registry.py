"""Tests for server.tools.registry — register/unregister/list tool functions."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml

from server.lib.models import Hook, HookRegistry
from server.lib.storage import load, save
from server.tools.registry import hooks_list, hooks_register, hooks_unregister


# ── hooks_register ───────────────────────────────────────────────────────────


class TestHooksRegister:
    def test_register_new_hook(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = hooks_register(
                trigger_tool="proj_init",
                target_tool="perms_setup",
                server="perms",
            )
        assert "Registered hook hook-001" in result
        assert "proj_init" in result
        assert "perms_setup" in result

        reg = load(hooks_yaml)
        assert len(reg.hooks) == 1
        assert reg.hooks[0].id == "hook-001"

    def test_register_with_param_mapping(self, hooks_yaml: Path):
        mapping = json.dumps({"path": "${result.path}"})
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = hooks_register(
                trigger_tool="proj_init",
                target_tool="perms_setup",
                server="perms",
                param_mapping=mapping,
            )
        assert "Registered" in result
        reg = load(hooks_yaml)
        assert reg.hooks[0].param_mapping == {"path": "${result.path}"}

    def test_register_blocking_hook(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = hooks_register(
                trigger_tool="t",
                target_tool="u",
                server="s",
                blocking=True,
            )
        assert "blocking: True" in result
        reg = load(hooks_yaml)
        assert reg.hooks[0].blocking is True

    def test_register_with_condition(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = hooks_register(
                trigger_tool="t",
                target_tool="u",
                server="s",
                condition="sync.enabled",
            )
        assert "condition: sync.enabled" in result
        reg = load(hooks_yaml)
        assert reg.hooks[0].condition == "sync.enabled"

    def test_register_duplicate_returns_existing(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(
                trigger_tool="proj_init",
                target_tool="perms_setup",
                server="perms",
            )
            result = hooks_register(
                trigger_tool="proj_init",
                target_tool="perms_setup",
                server="perms",
            )
        assert "Hook already exists" in result
        assert "hook-001" in result
        # Should still only have 1 hook
        reg = load(hooks_yaml)
        assert len(reg.hooks) == 1

    def test_register_invalid_json_param_mapping(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = hooks_register(
                trigger_tool="t",
                target_tool="u",
                server="s",
                param_mapping="not-json",
            )
        assert "Error" in result
        assert "not valid JSON" in result

    def test_register_non_dict_param_mapping(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = hooks_register(
                trigger_tool="t",
                target_tool="u",
                server="s",
                param_mapping="[1, 2, 3]",
            )
        assert "Error" in result
        assert "must be a JSON object" in result

    def test_register_cycle_detection(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(trigger_tool="A", target_tool="B", server="s")
            result = hooks_register(trigger_tool="B", target_tool="A", server="s")
        assert "Error" in result
        assert "cycle" in result.lower()

    def test_register_self_reference_rejected(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = hooks_register(trigger_tool="A", target_tool="A", server="s")
        assert "Error" in result
        assert "cycle" in result.lower() or "circular" in result.lower()

    def test_register_tracks_server(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(trigger_tool="t", target_tool="u", server="new-server")
        reg = load(hooks_yaml)
        assert "new-server" in reg.servers

    def test_register_increments_ids(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            hooks_register(trigger_tool="a", target_tool="b", server="s1")
            hooks_register(trigger_tool="c", target_tool="d", server="s2")
            hooks_register(trigger_tool="e", target_tool="f", server="s3")
        reg = load(hooks_yaml)
        ids = [h.id for h in reg.hooks]
        assert ids == ["hook-001", "hook-002", "hook-003"]


# ── hooks_list ───────────────────────────────────────────────────────────────


class TestHooksList:
    def test_list_empty(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = hooks_list()
        data = json.loads(result)
        assert data["hooks"] == []
        assert data["servers"] == {}

    def test_list_all(self, populated_hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", populated_hooks_yaml):
            result = hooks_list()
        data = json.loads(result)
        assert len(data["hooks"]) == 2
        assert "perms" in data["servers"]

    def test_list_filter_by_trigger(self, populated_hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", populated_hooks_yaml):
            result = hooks_list(trigger_tool="proj_init")
        data = json.loads(result)
        assert len(data["hooks"]) == 2
        for h in data["hooks"]:
            assert h["trigger_tool"] == "proj_init"

    def test_list_filter_no_match(self, populated_hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", populated_hooks_yaml):
            result = hooks_list(trigger_tool="nonexistent")
        data = json.loads(result)
        assert data["hooks"] == []

    def test_list_includes_condition_status(self, populated_hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", populated_hooks_yaml):
            result = hooks_list()
        data = json.loads(result)
        for h in data["hooks"]:
            assert "condition_status" in h
            assert h["condition_status"] in ("always", "active", "inactive")


# ── hooks_unregister ─────────────────────────────────────────────────────────


class TestHooksUnregister:
    def test_unregister_existing(self, populated_hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", populated_hooks_yaml):
            result = hooks_unregister("hook-001")
        assert "Unregistered hook hook-001" in result
        reg = load(populated_hooks_yaml)
        assert len(reg.hooks) == 1
        assert reg.find_by_id("hook-001") is None

    def test_unregister_not_found(self, hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", hooks_yaml):
            result = hooks_unregister("hook-999")
        assert "not found" in result

    def test_unregister_idempotent(self, populated_hooks_yaml: Path):
        with patch("server.lib.storage._HOOKS_FILE", populated_hooks_yaml):
            hooks_unregister("hook-001")
            result = hooks_unregister("hook-001")
        assert "not found" in result
