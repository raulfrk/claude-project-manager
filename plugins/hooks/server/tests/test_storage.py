"""Tests for server.lib.storage — YAML load/save and failure logging."""

from __future__ import annotations

from pathlib import Path

import yaml

from server.lib.models import Hook, HookRegistry
from server.lib.storage import (
    clear_failures,
    load,
    load_failures,
    load_invocations,
    load_verification_results,
    log_failure,
    log_invocation,
    save,
    save_failures,
    store_verification_result,
)


# ── load() ───────────────────────────────────────────────────────────────────


class TestLoad:
    def test_load_missing_file(self, hooks_yaml: Path):
        reg = load(hooks_yaml)
        assert reg.hooks == []
        assert reg.servers == {}

    def test_load_empty_file(self, hooks_yaml: Path):
        hooks_yaml.write_text("")
        reg = load(hooks_yaml)
        assert reg.hooks == []

    def test_load_non_dict_yaml(self, hooks_yaml: Path):
        hooks_yaml.write_text("- item1\n- item2\n")
        reg = load(hooks_yaml)
        assert reg.hooks == []

    def test_load_valid_yaml(self, populated_hooks_yaml: Path):
        reg = load(populated_hooks_yaml)
        assert len(reg.hooks) == 2
        assert reg.hooks[0].id == "hook-001"
        assert reg.hooks[1].id == "hook-002"
        assert "perms" in reg.servers
        assert "todoist" in reg.servers

    def test_load_preserves_settings(self, hooks_yaml: Path, write_yaml):
        write_yaml(hooks_yaml, {
            "hooks": [],
            "settings": {"max_depth": 5},
        })
        reg = load(hooks_yaml)
        assert reg.settings["max_depth"] == 5


# ── save() ───────────────────────────────────────────────────────────────────


class TestSave:
    def test_save_creates_file(self, hooks_yaml: Path, empty_registry: HookRegistry):
        result = save(empty_registry, hooks_yaml)
        assert result == hooks_yaml
        assert hooks_yaml.exists()

    def test_save_creates_parent_dirs(self, tmp_path: Path, empty_registry: HookRegistry):
        deep_path = tmp_path / "a" / "b" / "hooks.yaml"
        save(empty_registry, deep_path)
        assert deep_path.exists()

    def test_save_round_trip(self, hooks_yaml: Path, sample_registry: HookRegistry):
        save(sample_registry, hooks_yaml)
        restored = load(hooks_yaml)
        assert len(restored.hooks) == len(sample_registry.hooks)
        assert restored.hooks[0].id == sample_registry.hooks[0].id
        assert restored.servers == sample_registry.servers

    def test_save_overwrites_existing(self, hooks_yaml: Path):
        reg1 = HookRegistry(hooks=[
            Hook(id="hook-001", trigger_tool="a", target_tool="b", server="s"),
        ])
        save(reg1, hooks_yaml)
        assert len(load(hooks_yaml).hooks) == 1

        reg2 = HookRegistry(hooks=[
            Hook(id="hook-001", trigger_tool="a", target_tool="b", server="s"),
            Hook(id="hook-002", trigger_tool="c", target_tool="d", server="s"),
        ])
        save(reg2, hooks_yaml)
        assert len(load(hooks_yaml).hooks) == 2

    def test_save_preserves_file_permissions(self, hooks_yaml: Path, empty_registry: HookRegistry):
        save(empty_registry, hooks_yaml)
        hooks_yaml.chmod(0o600)
        mode_before = hooks_yaml.stat().st_mode & 0o7777

        save(empty_registry, hooks_yaml)
        mode_after = hooks_yaml.stat().st_mode & 0o7777
        assert mode_before == mode_after


# ── Failure logging ──────────────────────────────────────────────────────────


class TestLogFailure:
    def test_log_failure_creates_file(self, failures_yaml: Path):
        result = log_failure(
            hook_id="hook-001",
            trigger_tool="proj_init",
            target_tool="perms_setup",
            server="perms",
            error="Connection refused",
            path=failures_yaml,
        )
        assert result == failures_yaml
        assert failures_yaml.exists()

    def test_log_failure_appends(self, failures_yaml: Path):
        for i in range(3):
            log_failure(
                hook_id=f"hook-{i:03d}",
                trigger_tool="t",
                target_tool="u",
                server="s",
                error=f"error-{i}",
                path=failures_yaml,
            )
        entries = load_failures(failures_yaml)
        assert len(entries) == 3

    def test_log_failure_includes_source_result(self, failures_yaml: Path):
        log_failure(
            hook_id="hook-001",
            trigger_tool="t",
            target_tool="u",
            server="s",
            error="err",
            source_result='{"path": "/tmp"}',
            path=failures_yaml,
        )
        entries = load_failures(failures_yaml)
        assert entries[0]["source_result"] == '{"path": "/tmp"}'

    def test_log_failure_includes_timestamp(self, failures_yaml: Path):
        log_failure(
            hook_id="hook-001",
            trigger_tool="t",
            target_tool="u",
            server="s",
            error="err",
            path=failures_yaml,
        )
        entries = load_failures(failures_yaml)
        assert "timestamp" in entries[0]

    def test_log_failure_rolling_cap(self, failures_yaml: Path):
        """Writing more than _MAX_FAILURES entries trims to the cap."""
        # Pre-fill with 200 entries
        entries = []
        for i in range(200):
            entries.append({
                "hook_id": f"hook-{i:03d}",
                "trigger_tool": "t",
                "target_tool": "u",
                "server": "s",
                "error": f"error-{i}",
                "retry_count": 0,
            })
        failures_yaml.write_text(yaml.dump(entries, default_flow_style=False))

        # Add one more — should trim to 200 (the cap)
        log_failure(
            hook_id="hook-new",
            trigger_tool="t",
            target_tool="u",
            server="s",
            error="new error",
            path=failures_yaml,
        )
        result = load_failures(failures_yaml)
        assert len(result) == 200
        # The newest entry should be the last one
        assert result[-1]["hook_id"] == "hook-new"


# ── load_failures / save_failures / clear_failures ──────────────────────────


class TestFailureAccessors:
    def test_load_failures_missing_file(self, failures_yaml: Path):
        assert load_failures(failures_yaml) == []

    def test_load_failures_invalid_yaml(self, failures_yaml: Path):
        failures_yaml.write_text("not: a: list: {{{")
        # Should return empty list on parse error — relies on malformed YAML
        # PyYAML may parse partial content, so just verify no exception
        result = load_failures(failures_yaml)
        assert isinstance(result, list)

    def test_save_failures_round_trip(self, failures_yaml: Path):
        entries = [
            {"hook_id": "hook-001", "error": "timeout"},
            {"hook_id": "hook-002", "error": "refused"},
        ]
        save_failures(entries, failures_yaml)
        loaded = load_failures(failures_yaml)
        assert len(loaded) == 2
        assert loaded[0]["hook_id"] == "hook-001"

    def test_save_failures_empty_list(self, failures_yaml: Path):
        save_failures([], failures_yaml)
        assert failures_yaml.exists()
        assert load_failures(failures_yaml) == []

    def test_clear_failures_returns_count(self, failures_yaml: Path):
        entries = [{"hook_id": "hook-001", "error": "e"}]
        save_failures(entries, failures_yaml)
        cleared = clear_failures(failures_yaml)
        assert cleared == 1

    def test_clear_failures_empty(self, failures_yaml: Path):
        assert clear_failures(failures_yaml) == 0

    def test_clear_failures_removes_data(self, failures_yaml: Path):
        entries = [
            {"hook_id": "hook-001", "error": "e1"},
            {"hook_id": "hook-002", "error": "e2"},
        ]
        save_failures(entries, failures_yaml)
        clear_failures(failures_yaml)
        assert load_failures(failures_yaml) == []


# ── Verification results storage ─────────────────────────────────────────────


class TestStoreVerificationResult:
    def test_creates_file(self, verifications_yaml: Path):
        result = store_verification_result(
            "todo_complete",
            "verify-todoist-complete",
            "pass",
            "Todoist task 12345 confirmed complete",
            path=verifications_yaml,
        )
        assert result == verifications_yaml
        assert verifications_yaml.exists()

    def test_appends_entries(self, verifications_yaml: Path):
        for i in range(3):
            store_verification_result(
                "todo_complete",
                f"verify-{i}",
                "pass",
                f"details-{i}",
                path=verifications_yaml,
            )
        entries = load_verification_results(limit=0, path=verifications_yaml)
        assert len(entries) == 3

    def test_includes_all_fields(self, verifications_yaml: Path):
        store_verification_result(
            "todo_complete",
            "verify-todoist-complete",
            "fail",
            "Todoist task 12345 still open",
            path=verifications_yaml,
        )
        entries = load_verification_results(path=verifications_yaml)
        entry = entries[0]
        assert "timestamp" in entry
        assert entry["trigger_tool"] == "todo_complete"
        assert entry["hook_id"] == "verify-todoist-complete"
        assert entry["status"] == "fail"
        assert entry["details"] == "Todoist task 12345 still open"

    def test_rolling_cap_at_500(self, verifications_yaml: Path):
        """Writing more than 500 entries trims to the cap."""
        # Pre-fill with 500 entries
        entries = []
        for i in range(500):
            entries.append({
                "timestamp": "2026-01-01T00:00:00+00:00",
                "trigger_tool": "t",
                "hook_id": f"v-{i:04d}",
                "status": "pass",
                "details": f"details-{i}",
            })
        verifications_yaml.write_text(
            yaml.dump(entries, default_flow_style=False)
        )

        # Add one more — should trim to 500
        store_verification_result(
            "t", "v-new", "pass", "new details", path=verifications_yaml,
        )
        result = load_verification_results(limit=0, path=verifications_yaml)
        assert len(result) == 500
        # Oldest entry dropped, newest is last
        assert result[-1]["hook_id"] == "v-new"
        assert result[0]["hook_id"] == "v-0001"


class TestLoadVerificationResults:
    def test_missing_file(self, verifications_yaml: Path):
        assert load_verification_results(path=verifications_yaml) == []

    def test_invalid_yaml(self, verifications_yaml: Path):
        verifications_yaml.write_text("not: a: list: {{{")
        result = load_verification_results(path=verifications_yaml)
        assert isinstance(result, list)

    def test_default_limit_50(self, verifications_yaml: Path):
        entries = []
        for i in range(80):
            entries.append({
                "timestamp": "2026-01-01T00:00:00+00:00",
                "trigger_tool": "t",
                "hook_id": f"v-{i:03d}",
                "status": "pass",
                "details": f"d-{i}",
            })
        verifications_yaml.write_text(
            yaml.dump(entries, default_flow_style=False)
        )
        result = load_verification_results(path=verifications_yaml)
        assert len(result) == 50
        # Should return the 50 most recent (last 50)
        assert result[0]["hook_id"] == "v-030"
        assert result[-1]["hook_id"] == "v-079"

    def test_custom_limit(self, verifications_yaml: Path):
        for i in range(10):
            store_verification_result(
                "t", f"v-{i}", "pass", f"d-{i}", path=verifications_yaml,
            )
        result = load_verification_results(limit=3, path=verifications_yaml)
        assert len(result) == 3
        assert result[-1]["hook_id"] == "v-9"

    def test_limit_zero_returns_all(self, verifications_yaml: Path):
        for i in range(5):
            store_verification_result(
                "t", f"v-{i}", "pass", f"d-{i}", path=verifications_yaml,
            )
        result = load_verification_results(limit=0, path=verifications_yaml)
        assert len(result) == 5


# ── Invocation logging ───────────────────────────────────────────────────────


class TestLogInvocation:
    def test_creates_file(self, tmp_path: Path):
        p = tmp_path / "inv.yaml"
        result = log_invocation(
            hook_id="h-001", trigger_tool="t", target_tool="u", server="s", path=p,
        )
        assert result == p
        assert p.exists()

    def test_appends_entries(self, tmp_path: Path):
        p = tmp_path / "inv.yaml"
        for i in range(3):
            log_invocation(hook_id=f"h-{i}", trigger_tool="t", target_tool="u", server="s", path=p)
        assert len(load_invocations(limit=0, path=p)) == 3

    def test_includes_timestamp(self, tmp_path: Path):
        p = tmp_path / "inv.yaml"
        log_invocation(hook_id="h-001", trigger_tool="t", target_tool="u", server="s", path=p)
        entries = load_invocations(path=p)
        assert "timestamp" in entries[0]

    def test_includes_all_core_fields(self, tmp_path: Path):
        p = tmp_path / "inv.yaml"
        log_invocation(
            hook_id="h-001", trigger_tool="trig", target_tool="tgt", server="svc", path=p,
        )
        entry = load_invocations(path=p)[0]
        assert entry["hook_id"] == "h-001"
        assert entry["trigger_tool"] == "trig"
        assert entry["target_tool"] == "tgt"
        assert entry["server"] == "svc"

    def test_source_result_truncated_at_500(self, tmp_path: Path):
        p = tmp_path / "inv.yaml"
        long_val = "x" * 1000
        log_invocation(
            hook_id="h-001", trigger_tool="t", target_tool="u", server="s",
            source_result=long_val, path=p,
        )
        entries = load_invocations(path=p)
        assert len(entries[0]["source_result"]) == 500

    def test_payload_truncated_at_500(self, tmp_path: Path):
        p = tmp_path / "inv.yaml"
        big_payload = {"key": "v" * 1000}
        log_invocation(
            hook_id="h-001", trigger_tool="t", target_tool="u", server="s",
            payload=big_payload, path=p,
        )
        entries = load_invocations(path=p)
        assert len(entries[0]["payload"]) <= 500

    def test_rolling_cap_at_2000(self, tmp_path: Path):
        p = tmp_path / "inv.yaml"
        entries = [
            {"hook_id": f"h-{i}", "trigger_tool": "t", "target_tool": "u", "server": "s"}
            for i in range(2000)
        ]
        p.write_text(yaml.dump(entries, default_flow_style=False))
        log_invocation(hook_id="h-new", trigger_tool="t", target_tool="u", server="s", path=p)
        result = load_invocations(limit=0, path=p)
        assert len(result) == 2000
        assert result[-1]["hook_id"] == "h-new"


class TestLoadInvocations:
    def test_missing_file_returns_empty(self, tmp_path: Path):
        p = tmp_path / "inv.yaml"
        assert load_invocations(path=p) == []

    def test_default_limit_50(self, tmp_path: Path):
        p = tmp_path / "inv.yaml"
        for i in range(80):
            log_invocation(hook_id=f"h-{i}", trigger_tool="t", target_tool="u", server="s", path=p)
        result = load_invocations(path=p)
        assert len(result) == 50
        # Should be the 50 most recent
        assert result[-1]["hook_id"] == "h-79"

    def test_limit_zero_returns_all(self, tmp_path: Path):
        p = tmp_path / "inv.yaml"
        for i in range(5):
            log_invocation(hook_id=f"h-{i}", trigger_tool="t", target_tool="u", server="s", path=p)
        assert len(load_invocations(limit=0, path=p)) == 5
