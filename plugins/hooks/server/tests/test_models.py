"""Tests for server.lib.models — Hook and HookRegistry dataclasses."""

from __future__ import annotations

from server.lib.models import Hook, HookRegistry

# ── Hook dataclass ────────────────────────────────────────────────────────────


class TestHook:
    def test_defaults(self):
        h = Hook(id="hook-001", trigger_tool="a", target_tool="b", server="s")
        assert h.param_mapping == {}
        assert h.blocking is False
        assert h.condition is None
        assert h.source is None
        assert h.verification is False

    def test_to_dict_minimal(self):
        h = Hook(id="hook-001", trigger_tool="a", target_tool="b", server="s")
        d = h.to_dict()
        assert d == {
            "id": "hook-001",
            "trigger_tool": "a",
            "target_tool": "b",
            "server": "s",
            "param_mapping": {},
            "blocking": False,
        }
        # condition and source omitted when None
        assert "condition" not in d
        assert "source" not in d

    def test_to_dict_with_optional_fields(self):
        h = Hook(
            id="hook-005",
            trigger_tool="t",
            target_tool="u",
            server="sv",
            param_mapping={"x": "${y}"},
            blocking=True,
            condition="sync.enabled",
            source="auto",
        )
        d = h.to_dict()
        assert d["condition"] == "sync.enabled"
        assert d["source"] == "auto"
        assert d["blocking"] is True

    def test_from_dict_round_trip(self):
        original = Hook(
            id="hook-010",
            trigger_tool="trigger",
            target_tool="target",
            server="srv",
            param_mapping={"path": "${result.path}"},
            blocking=True,
            condition="flag",
            source="auto",
        )
        d = original.to_dict()
        restored = Hook.from_dict(d)
        assert restored.id == original.id
        assert restored.trigger_tool == original.trigger_tool
        assert restored.target_tool == original.target_tool
        assert restored.server == original.server
        assert restored.param_mapping == original.param_mapping
        assert restored.blocking == original.blocking
        assert restored.condition == original.condition
        assert restored.source == original.source
        assert restored.verification == original.verification

    def test_from_dict_missing_fields_defaults(self):
        h = Hook.from_dict({})
        assert h.id == ""
        assert h.trigger_tool == ""
        assert h.target_tool == ""
        assert h.server == ""
        assert h.param_mapping == {}
        assert h.blocking is False
        assert h.condition is None
        assert h.source is None
        assert h.verification is False

    def test_from_dict_preserves_param_mapping_values(self):
        h = Hook.from_dict(
            {
                "id": "hook-001",
                "trigger_tool": "a",
                "target_tool": "b",
                "server": "s",
                "param_mapping": {"num": 42, "flag": True},
            }
        )
        assert h.param_mapping == {"num": 42, "flag": True}

    def test_from_dict_ignores_non_dict_param_mapping(self):
        h = Hook.from_dict(
            {
                "id": "hook-001",
                "trigger_tool": "a",
                "target_tool": "b",
                "server": "s",
                "param_mapping": "not-a-dict",
            }
        )
        assert h.param_mapping == {}

    def test_matches(self, sample_hook: Hook):
        assert sample_hook.matches("proj_init", "perms_setup", "perms") is True
        assert sample_hook.matches("proj_init", "perms_setup", "other") is False
        assert sample_hook.matches("proj_init", "other", "perms") is False
        assert sample_hook.matches("other", "perms_setup", "perms") is False

    def test_verification_forces_blocking_true(self):
        h = Hook(
            id="hook-v01",
            trigger_tool="todo_complete",
            target_tool="todoist_verify",
            server="todoist",
            blocking=False,
            verification=True,
        )
        assert h.verification is True
        assert h.blocking is True

    def test_verification_false_preserves_explicit_blocking(self):
        h = Hook(
            id="hook-001",
            trigger_tool="a",
            target_tool="b",
            server="s",
            blocking=True,
            verification=False,
        )
        assert h.verification is False
        assert h.blocking is True

    def test_to_dict_includes_verification_when_true(self):
        h = Hook(
            id="hook-v01",
            trigger_tool="t",
            target_tool="u",
            server="sv",
            verification=True,
        )
        d = h.to_dict()
        assert d["verification"] is True
        assert d["blocking"] is True

    def test_to_dict_omits_verification_when_false(self):
        h = Hook(id="hook-001", trigger_tool="a", target_tool="b", server="s")
        d = h.to_dict()
        assert "verification" not in d

    def test_from_dict_verification_true_round_trip(self):
        original = Hook(
            id="hook-v01",
            trigger_tool="todo_complete",
            target_tool="todoist_verify",
            server="todoist",
            verification=True,
        )
        d = original.to_dict()
        restored = Hook.from_dict(d)
        assert restored.verification is True
        assert restored.blocking is True

    # ── feedback_mapping & feedback_tool ─────────────────────────────────────

    def test_feedback_fields_default_empty(self):
        h = Hook(id="hook-001", trigger_tool="a", target_tool="b", server="s")
        assert h.feedback_mapping == {}
        assert h.feedback_tool is None

    def test_to_dict_includes_feedback_fields(self):
        h = Hook(
            id="hook-001",
            trigger_tool="a",
            target_tool="b",
            server="s",
            feedback_mapping={"status": "${result.ok}"},
            feedback_tool="check_result",
        )
        d = h.to_dict()
        assert d["feedback_mapping"] == {"status": "${result.ok}"}
        assert d["feedback_tool"] == "check_result"

    def test_to_dict_omits_empty_feedback(self):
        h = Hook(id="hook-001", trigger_tool="a", target_tool="b", server="s")
        d = h.to_dict()
        assert "feedback_mapping" not in d
        assert "feedback_tool" not in d

    def test_from_dict_feedback_round_trip(self):
        original = Hook(
            id="hook-001",
            trigger_tool="a",
            target_tool="b",
            server="s",
            feedback_mapping={"x": "${y}"},
            feedback_tool="fb_tool",
        )
        restored = Hook.from_dict(original.to_dict())
        assert restored.feedback_mapping == {"x": "${y}"}
        assert restored.feedback_tool == "fb_tool"

    def test_from_dict_ignores_non_dict_feedback_mapping(self):
        h = Hook.from_dict(
            {
                "id": "hook-001",
                "trigger_tool": "a",
                "target_tool": "b",
                "server": "s",
                "feedback_mapping": "bad",
            }
        )
        assert h.feedback_mapping == {}

    # ── update_from ───────────────────────────────────────────────────────────

    def test_update_from_changes_blocking(self):
        h = Hook(id="hook-001", trigger_tool="a", target_tool="b", server="s")
        h.update_from({"blocking": True})
        assert h.blocking is True

    def test_update_from_preserves_identity_fields(self):
        h = Hook(id="hook-001", trigger_tool="a", target_tool="b", server="s", source="auto")
        h.update_from({"blocking": True, "condition": "flag"})
        assert h.id == "hook-001"
        assert h.trigger_tool == "a"
        assert h.target_tool == "b"
        assert h.server == "s"
        assert h.source == "auto"

    def test_update_from_param_mapping(self):
        h = Hook(
            id="hook-001",
            trigger_tool="a",
            target_tool="b",
            server="s",
            param_mapping={"old": "val"},
        )
        h.update_from({"param_mapping": {"new": "${x}"}})
        assert h.param_mapping == {"new": "${x}"}

    def test_update_from_verification_forces_blocking(self):
        h = Hook(id="hook-001", trigger_tool="a", target_tool="b", server="s")
        h.update_from({"verification": True, "blocking": False})
        assert h.verification is True
        assert h.blocking is True

    def test_update_from_feedback_fields(self):
        h = Hook(id="hook-001", trigger_tool="a", target_tool="b", server="s")
        h.update_from({"feedback_tool": "fb", "feedback_mapping": {"k": "v"}})
        assert h.feedback_tool == "fb"
        assert h.feedback_mapping == {"k": "v"}

    def test_update_from_non_dict_param_mapping_clears(self):
        h = Hook(
            id="hook-001",
            trigger_tool="a",
            target_tool="b",
            server="s",
            param_mapping={"old": "val"},
        )
        h.update_from({"param_mapping": "not-a-dict"})
        assert h.param_mapping == {}

    def test_from_dict_coerces_non_string_condition(self):
        h = Hook.from_dict(
            {
                "id": "hook-001",
                "trigger_tool": "a",
                "target_tool": "b",
                "server": "s",
                "condition": 42,
            }
        )
        assert h.condition == "42"


# ── HookRegistry dataclass ───────────────────────────────────────────────────


class TestHookRegistry:
    def test_empty_registry(self, empty_registry: HookRegistry):
        assert empty_registry.hooks == []
        assert empty_registry.servers == {}
        assert empty_registry.settings == {}

    def test_to_dict_empty(self, empty_registry: HookRegistry):
        d = empty_registry.to_dict()
        assert d["hooks"] == []
        assert "servers" not in d
        assert "settings" not in d

    def test_to_dict_populated(self, sample_registry: HookRegistry):
        d = sample_registry.to_dict()
        assert len(d["hooks"]) == 2
        assert "perms" in d["servers"]
        assert d["settings"]["max_depth"] == 3

    def test_from_dict_round_trip(self, sample_registry: HookRegistry):
        d = sample_registry.to_dict()
        restored = HookRegistry.from_dict(d)
        assert len(restored.hooks) == len(sample_registry.hooks)
        assert restored.servers == sample_registry.servers
        assert restored.settings == sample_registry.settings

    def test_from_dict_bad_hooks_type(self):
        reg = HookRegistry.from_dict({"hooks": "not-a-list"})
        assert reg.hooks == []

    def test_from_dict_skips_non_dict_hook_entries(self):
        reg = HookRegistry.from_dict({"hooks": [{"id": "hook-001"}, "bad", 42]})
        assert len(reg.hooks) == 1

    def test_from_dict_bad_servers_type(self):
        reg = HookRegistry.from_dict({"servers": "not-a-dict"})
        assert reg.servers == {}

    def test_from_dict_skips_non_dict_server_entries(self):
        reg = HookRegistry.from_dict({"servers": {"good": {"url": "http://x"}, "bad": "string"}})
        assert "good" in reg.servers
        assert "bad" not in reg.servers

    def test_from_dict_bad_settings_type(self):
        reg = HookRegistry.from_dict({"settings": [1, 2, 3]})
        assert reg.settings == {}

    def test_next_id_empty(self, empty_registry: HookRegistry):
        assert empty_registry.next_id() == "hook-001"

    def test_next_id_increments(self, sample_registry: HookRegistry):
        # sample_registry has hook-001 and hook-002
        assert sample_registry.next_id() == "hook-003"

    def test_next_id_handles_non_numeric_ids(self):
        reg = HookRegistry(
            hooks=[
                Hook(id="hook-abc", trigger_tool="a", target_tool="b", server="s"),
                Hook(id="hook-005", trigger_tool="c", target_tool="d", server="s"),
            ]
        )
        assert reg.next_id() == "hook-006"

    def test_find_duplicate_found(self, sample_registry: HookRegistry):
        dup = sample_registry.find_duplicate("proj_init", "perms_setup", "perms")
        assert dup is not None
        assert dup.id == "hook-001"

    def test_find_duplicate_not_found(self, sample_registry: HookRegistry):
        assert sample_registry.find_duplicate("x", "y", "z") is None

    def test_find_by_id_found(self, sample_registry: HookRegistry):
        h = sample_registry.find_by_id("hook-002")
        assert h is not None
        assert h.target_tool == "todoist_sync"

    def test_find_by_id_not_found(self, sample_registry: HookRegistry):
        assert sample_registry.find_by_id("hook-999") is None

    def test_remove_by_id_found(self, sample_registry: HookRegistry):
        assert sample_registry.remove_by_id("hook-001") is True
        assert len(sample_registry.hooks) == 1
        assert sample_registry.find_by_id("hook-001") is None

    def test_remove_by_id_not_found(self, sample_registry: HookRegistry):
        assert sample_registry.remove_by_id("hook-999") is False
        assert len(sample_registry.hooks) == 2
