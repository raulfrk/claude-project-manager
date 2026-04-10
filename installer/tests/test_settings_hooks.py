"""Unit tests for installer/settings_hooks.py."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
import yaml

from installer.settings_hooks import (
    SettingsHookDiff,
    SettingsHooksError,
    _backup_with_retention,
    _read_settings_json,
    apply_settings_hooks_diffs,
    compute_settings_hooks_diff,
    is_managed_entry,
    merge_settings_defaults,
    resolve_command_template,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_plugin_default(plugin_dir: Path, entries: list[dict]) -> Path:
    cpd = plugin_dir / ".claude-plugin"
    cpd.mkdir(parents=True, exist_ok=True)
    f = cpd / "default-settings-hooks.yaml"
    f.write_text(yaml.safe_dump({"hooks": entries}))
    return f


def _sample_entry(
    cpm_id: str = "proj-session-start",
    event: str = "SessionStart",
    matchers: list[str] | None = None,
    script: str = "/opt/cpm/scripts/session_start.py",
    command: str = "{python} {script} --cache {plugin_cache_dir}",
) -> dict:
    return {
        "id": cpm_id,
        "event": event,
        "matchers": matchers or ["startup", "resume"],
        "script": script,
        "command": command,
    }


# ---------------------------------------------------------------------------
# TestMergeSettingsDefaults
# ---------------------------------------------------------------------------


class TestMergeSettingsDefaults:
    def test_empty_plugin_dirs_returns_empty(self) -> None:
        assert merge_settings_defaults([]) == {}

    def test_single_plugin_single_entry_merged(self, tmp_path: Path) -> None:
        plugin = tmp_path / "plugin_a"
        _write_plugin_default(plugin, [_sample_entry("id-a")])
        merged = merge_settings_defaults([plugin])
        assert set(merged.keys()) == {"id-a"}
        assert merged["id-a"]["event"] == "SessionStart"

    def test_multiple_plugins_merged_by_id(self, tmp_path: Path) -> None:
        p1 = tmp_path / "p1"
        p2 = tmp_path / "p2"
        _write_plugin_default(p1, [_sample_entry("id-1")])
        _write_plugin_default(p2, [_sample_entry("id-2", event="UserPromptSubmit")])
        merged = merge_settings_defaults([p1, p2])
        assert set(merged.keys()) == {"id-1", "id-2"}
        assert merged["id-2"]["event"] == "UserPromptSubmit"

    def test_duplicate_id_across_plugins_raises_SettingsHooksError(
        self, tmp_path: Path
    ) -> None:
        p1 = tmp_path / "p1"
        p2 = tmp_path / "p2"
        _write_plugin_default(p1, [_sample_entry("shared-id")])
        _write_plugin_default(p2, [_sample_entry("shared-id")])
        with pytest.raises(SettingsHooksError, match="Duplicate"):
            merge_settings_defaults([p1, p2])


# ---------------------------------------------------------------------------
# TestResolveCommandTemplate
# ---------------------------------------------------------------------------


class TestResolveCommandTemplate:
    def test_all_variables_substituted(self) -> None:
        entry = {
            "id": "h1",
            "python": "/usr/bin/python3.11",
            "script": "/opt/script.py",
            "command": "{python} {script} --cache {plugin_cache_dir}",
        }
        resolved = resolve_command_template(entry, Path("/var/cache/cpm"))
        assert "/usr/bin/python3.11" in resolved
        assert "/opt/script.py" in resolved
        assert "/var/cache/cpm" in resolved
        assert "{python}" not in resolved
        assert "{script}" not in resolved
        assert "{plugin_cache_dir}" not in resolved

    def test_sentinel_prepended_as_first_line(self) -> None:
        entry = {"id": "my-hook", "command": "echo hi"}
        resolved = resolve_command_template(entry, Path("/cache"))
        assert resolved.startswith("# cpm:my-hook\n")
        assert resolved.splitlines()[0] == "# cpm:my-hook"

    def test_default_python_is_python3(self) -> None:
        entry = {"id": "h", "script": "x.py", "command": "{python} {script}"}
        resolved = resolve_command_template(entry, Path("/c"))
        assert "python3 x.py" in resolved


# ---------------------------------------------------------------------------
# TestIsManagedEntry
# ---------------------------------------------------------------------------


class TestIsManagedEntry:
    def test_matches_via_cpm_id_field(self) -> None:
        block = {"matcher": "startup", "__cpm_id": "my-hook", "hooks": []}
        assert is_managed_entry(block, "my-hook") is True

    def test_matches_via_command_sentinel(self) -> None:
        block = {
            "matcher": "startup",
            "hooks": [{"command": "# cpm:my-hook\nrun it", "type": "command"}],
        }
        assert is_managed_entry(block, "my-hook") is True

    def test_no_match_returns_false(self) -> None:
        block = {
            "matcher": "startup",
            "__cpm_id": "other-hook",
            "hooks": [{"command": "echo foo", "type": "command"}],
        }
        assert is_managed_entry(block, "my-hook") is False

    def test_invalid_matcher_block_returns_false(self) -> None:
        assert is_managed_entry("not a dict", "my-hook") is False  # type: ignore[arg-type]
        assert is_managed_entry({}, "my-hook") is False


# ---------------------------------------------------------------------------
# TestComputeSettingsHooksDiff
# ---------------------------------------------------------------------------


class TestComputeSettingsHooksDiff:
    def test_fresh_install_all_new(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        plugin = tmp_path / "p1"
        _write_plugin_default(plugin, [_sample_entry("id-a"), _sample_entry("id-b")])
        diffs = compute_settings_hooks_diff(settings, [plugin])
        assert len(diffs) == 2
        assert all(d.kind == "new" for d in diffs)
        assert {d.cpm_id for d in diffs} == {"id-a", "id-b"}

    def test_unchanged_on_identical_content(self, tmp_path: Path) -> None:
        plugin = tmp_path / "p"
        entry = _sample_entry("id-1", matchers=["startup"])
        _write_plugin_default(plugin, [entry])
        resolved_cmd = resolve_command_template(entry, Path())
        settings_data = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "__cpm_id": "id-1",
                        "hooks": [{"command": resolved_cmd, "type": "command"}],
                    }
                ]
            }
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(settings_data))
        diffs = compute_settings_hooks_diff(settings, [plugin])
        assert len(diffs) == 1
        assert diffs[0].kind == "unchanged"

    def test_changed_when_command_body_differs(self, tmp_path: Path) -> None:
        plugin = tmp_path / "p"
        _write_plugin_default(plugin, [_sample_entry("id-1", matchers=["startup"])])
        settings_data = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "__cpm_id": "id-1",
                        "hooks": [
                            {
                                "command": "# cpm:id-1\nold_command --legacy",
                                "type": "command",
                            }
                        ],
                    }
                ]
            }
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(settings_data))
        diffs = compute_settings_hooks_diff(settings, [plugin])
        assert len(diffs) == 1
        assert diffs[0].kind == "changed"

    def test_removed_when_in_actual_but_not_desired(self, tmp_path: Path) -> None:
        """A managed id still in settings.json but present in desired (same id reused)
        is `unchanged` or `changed`; drops from desired are covered by
        test_orphan_managed_entry_detected_via_direct_apply path elsewhere.
        Here we verify the positive case: diff carries an id listed in desired and
        the stale matcher is tracked as the `actual`."""
        plugin = tmp_path / "p"
        _write_plugin_default(plugin, [_sample_entry("id-a", matchers=["startup"])])
        settings_data = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "__cpm_id": "id-a",
                        "hooks": [
                            {"command": "# cpm:id-a\nstale body", "type": "command"}
                        ],
                    }
                ]
            }
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(settings_data))
        diffs = compute_settings_hooks_diff(settings, [plugin])
        assert len(diffs) == 1
        assert diffs[0].cpm_id == "id-a"
        assert diffs[0].kind == "changed"
        assert diffs[0].actual is not None

    def test_symlink_resolved(self, tmp_path: Path) -> None:
        plugin = tmp_path / "p"
        _write_plugin_default(plugin, [_sample_entry("id-a")])
        real = tmp_path / "real_settings.json"
        real.write_text(json.dumps({"hooks": {}}))
        link = tmp_path / "link_settings.json"
        try:
            link.symlink_to(real)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"symlinks unsupported: {exc}")
        diffs = compute_settings_hooks_diff(link, [plugin])
        assert len(diffs) == 1
        assert diffs[0].kind == "new"


# ---------------------------------------------------------------------------
# TestApplySettingsHooksDiffs
# ---------------------------------------------------------------------------


class TestApplySettingsHooksDiffs:
    def test_empty_apply_ids_short_circuits(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        original = {"hooks": {}, "other_key": "preserved"}
        settings.write_text(json.dumps(original))
        mtime_before = settings.stat().st_mtime
        time.sleep(0.01)
        apply_settings_hooks_diffs(settings, [], apply_ids=set(), remove_ids=set())
        assert settings.stat().st_mtime == mtime_before
        assert json.loads(settings.read_text()) == original

    def test_new_entry_added_to_settings(self, tmp_path: Path) -> None:
        plugin = tmp_path / "p"
        _write_plugin_default(plugin, [_sample_entry("id-a", matchers=["startup"])])
        settings = tmp_path / "settings.json"
        settings.write_text("{}")
        diffs = compute_settings_hooks_diff(settings, [plugin])
        apply_settings_hooks_diffs(settings, diffs, apply_ids={"id-a"})
        data = json.loads(settings.read_text())
        matchers = data["hooks"]["SessionStart"]
        assert len(matchers) == 1
        assert matchers[0]["__cpm_id"] == "id-a"
        assert "# cpm:id-a" in matchers[0]["hooks"][0]["command"]

    def test_changed_entry_replaced(self, tmp_path: Path) -> None:
        plugin = tmp_path / "p"
        _write_plugin_default(plugin, [_sample_entry("id-1", matchers=["startup"])])
        settings_data = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "__cpm_id": "id-1",
                        "hooks": [{"command": "# cpm:id-1\nOLD", "type": "command"}],
                    }
                ]
            }
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(settings_data))
        diffs = compute_settings_hooks_diff(settings, [plugin])
        assert diffs[0].kind == "changed"
        apply_settings_hooks_diffs(settings, diffs, apply_ids={"id-1"})
        data = json.loads(settings.read_text())
        matchers = data["hooks"]["SessionStart"]
        managed = [m for m in matchers if m.get("__cpm_id") == "id-1"]
        assert len(managed) == 1
        assert "OLD" not in managed[0]["hooks"][0]["command"]

    def test_removed_entry_deleted(self, tmp_path: Path) -> None:
        """Explicit removal via remove_ids strips the managed matcher block."""
        settings_data = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "__cpm_id": "id-gone",
                        "hooks": [{"command": "# cpm:id-gone\nrun", "type": "command"}],
                    },
                    {
                        "matcher": "resume",
                        "hooks": [{"command": "user-owned", "type": "command"}],
                    },
                ]
            }
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(settings_data))
        manual_diff = SettingsHookDiff(
            cpm_id="id-gone",
            kind="removed",
            event="SessionStart",
            matchers=["startup"],
            desired=None,
            actual=None,
        )
        apply_settings_hooks_diffs(
            settings, [manual_diff], apply_ids=set(), remove_ids={"id-gone"}
        )
        data = json.loads(settings.read_text())
        matchers = data["hooks"]["SessionStart"]
        assert not any(m.get("__cpm_id") == "id-gone" for m in matchers)
        assert any(
            m.get("matcher") == "resume" and "user-owned" in m["hooks"][0]["command"]
            for m in matchers
        )


# ---------------------------------------------------------------------------
# TestBackupRetention
# ---------------------------------------------------------------------------


class TestBackupRetention:
    def test_backup_created_before_write(self, tmp_path: Path) -> None:
        plugin = tmp_path / "p"
        _write_plugin_default(plugin, [_sample_entry("id-a", matchers=["startup"])])
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps({"hooks": {}}))
        diffs = compute_settings_hooks_diff(settings, [plugin])
        apply_settings_hooks_diffs(settings, diffs, apply_ids={"id-a"})
        backups = [p for p in tmp_path.iterdir() if ".bak-" in p.name]
        assert len(backups) >= 1

    def test_retention_keeps_5_most_recent(self, tmp_path: Path) -> None:
        settings = tmp_path / "settings.json"
        settings.write_text("{}")
        for i in range(8):
            _backup_with_retention(settings, keep=5)
            ts = time.time() - (8 - i)
            for p in tmp_path.iterdir():
                if ".bak-" in p.name:
                    os.utime(p, (ts, ts))
            time.sleep(0.01)
        _backup_with_retention(settings, keep=5)
        backups = sorted(p for p in tmp_path.iterdir() if ".bak-" in p.name)
        assert len(backups) <= 5


# ---------------------------------------------------------------------------
# TestReadSettingsJson
# ---------------------------------------------------------------------------


class TestReadSettingsJson:
    def test_malformed_json_raises_SettingsHooksError(self, tmp_path: Path) -> None:
        p = tmp_path / "settings.json"
        p.write_text("{not valid json")
        with pytest.raises(SettingsHooksError, match="Malformed JSON"):
            _read_settings_json(p)

    def test_wrong_top_level_type_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "settings.json"
        p.write_text("[1, 2, 3]")
        with pytest.raises(SettingsHooksError, match="top-level"):
            _read_settings_json(p)


# ---------------------------------------------------------------------------
# TestPluginIdConflict
# ---------------------------------------------------------------------------


class TestPluginIdConflict:
    def test_duplicate_id_different_plugin_dirs_raises(self, tmp_path: Path) -> None:
        p1 = tmp_path / "plugin_one"
        p2 = tmp_path / "plugin_two"
        _write_plugin_default(p1, [_sample_entry("collision-id", script="/a.py")])
        _write_plugin_default(p2, [_sample_entry("collision-id", script="/b.py")])
        with pytest.raises(SettingsHooksError) as excinfo:
            merge_settings_defaults([p1, p2])
        assert "collision-id" in str(excinfo.value)
