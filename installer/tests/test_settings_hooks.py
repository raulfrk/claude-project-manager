"""Unit tests for installer/settings_hooks.py."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest
import yaml

from installer.settings_hooks import (
    SettingsDocument,
    SettingsHookDiff,
    SettingsHooksError,
    _backup_with_retention,
    _extract_cpm_id_from_command,
    _read_settings_json,
    apply_settings_hooks_diffs,
    compute_settings_hooks_diff,
    discover_managed_ids,
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
        # Use plugin dir (not Path()) — after fix, merge_settings_defaults stores
        # _source_plugin_dir=plugin and resolve_command_template uses it for comparison.
        resolved_cmd = resolve_command_template(entry, plugin)
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
        """Orphan managed entry (in settings.json, NOT in any plugin default)
        MUST surface as a `removed` diff. This is the regression fix for the
        previously-unreachable `removed` branch — see todo 517."""
        plugin = tmp_path / "p"
        # Desired contains id-a only; settings.json contains id-a (unchanged)
        # PLUS an orphan id-gone that has no corresponding plugin default.
        entry = _sample_entry("id-a", matchers=["startup"])
        _write_plugin_default(plugin, [entry])
        # Use plugin dir — after fix, _source_plugin_dir=plugin is used for comparison.
        resolved_cmd = resolve_command_template(entry, plugin)
        settings_data = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "__cpm_id": "id-a",
                        "hooks": [{"command": resolved_cmd, "type": "command"}],
                    },
                    {
                        "matcher": "startup",
                        "__cpm_id": "id-gone",
                        "hooks": [{"command": "# cpm:id-gone\nrun", "type": "command"}],
                    },
                ]
            }
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(settings_data))
        diffs = compute_settings_hooks_diff(settings, [plugin])
        by_id = {d.cpm_id: d for d in diffs}
        assert set(by_id) == {"id-a", "id-gone"}
        assert by_id["id-a"].kind == "unchanged"
        orphan = by_id["id-gone"]
        assert orphan.kind == "removed"
        assert orphan.event == "SessionStart"
        assert orphan.desired is None
        assert orphan.actual is not None
        assert orphan.actual["event"] == "SessionStart"
        assert orphan.matchers == ["startup"]

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
# TestDiscoverManagedIds — new unit tests for the orphan-detection helper.
# ---------------------------------------------------------------------------


def _doc_with_events(events: dict[str, list[dict]]) -> SettingsDocument:
    return SettingsDocument.from_dict(
        Path("/tmp/nonexistent/settings.json"), {"hooks": events}
    )


class TestDiscoverManagedIds:
    def test_discover_managed_ids_prefix_collision(self) -> None:
        """`foo` vs `foobar` must not match each other — anchored regex."""
        doc = _doc_with_events(
            {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "hooks": [{"command": "# cpm:foobar\nrun", "type": "command"}],
                    }
                ]
            }
        )
        discovered = discover_managed_ids(doc)
        assert discovered == [
            ("SessionStart", "foobar", doc.hooks.events["SessionStart"][0])
        ]
        # is_managed_entry must not prefix-match either
        assert not is_managed_entry(doc.hooks.events["SessionStart"][0], "foo")
        assert is_managed_entry(doc.hooks.events["SessionStart"][0], "foobar")

    def test_discover_managed_ids_cross_event_collision(self, tmp_path: Path) -> None:
        """foo desired in SessionStart + foo orphan in SessionEnd →
        compute emits removed diff ONLY for SessionEnd and preserves
        SessionStart as unchanged/changed/new."""
        plugin = tmp_path / "p"
        entry = _sample_entry("foo", event="SessionStart", matchers=["startup"])
        _write_plugin_default(plugin, [entry])
        # Use plugin dir so stored command matches what compute_settings_hooks_diff expects.
        resolved_cmd = resolve_command_template(entry, plugin)
        settings_data = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "__cpm_id": "foo",
                        "hooks": [{"command": resolved_cmd, "type": "command"}],
                    }
                ],
                "SessionEnd": [
                    {
                        "matcher": "shutdown",
                        "__cpm_id": "foo",
                        "hooks": [{"command": "# cpm:foo\nstale", "type": "command"}],
                    }
                ],
            }
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(settings_data))
        diffs = compute_settings_hooks_diff(settings, [plugin])
        by_key = {(d.event, d.cpm_id): d for d in diffs}
        assert set(by_key) == {("SessionStart", "foo"), ("SessionEnd", "foo")}
        assert by_key[("SessionStart", "foo")].kind == "unchanged"
        assert by_key[("SessionEnd", "foo")].kind == "removed"
        assert by_key[("SessionEnd", "foo")].matchers == ["shutdown"]

    def test_discover_managed_ids_duplicate_occurrence(self, tmp_path: Path) -> None:
        """Same cpm_id in 2+ matchers within one event → discover returns
        BOTH tuples; compute emits ONE removed diff via seen-set guard."""
        settings_data = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "__cpm_id": "orphan",
                        "hooks": [{"command": "# cpm:orphan\nrun1", "type": "command"}],
                    },
                    {
                        "matcher": "resume",
                        "__cpm_id": "orphan",
                        "hooks": [{"command": "# cpm:orphan\nrun2", "type": "command"}],
                    },
                ]
            }
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(settings_data))
        # discover returns both occurrences
        doc = SettingsDocument.from_dict(settings, json.loads(settings.read_text()))
        discovered = discover_managed_ids(doc)
        assert len(discovered) == 2
        assert all(t[1] == "orphan" for t in discovered)
        # compute emits ONE removed diff (with mass_remove=True since
        # desired is empty in this test)
        plugin = tmp_path / "empty_plugin"
        plugin.mkdir()
        diffs = compute_settings_hooks_diff(settings, [plugin], mass_remove=True)
        orphan_diffs = [d for d in diffs if d.cpm_id == "orphan"]
        assert len(orphan_diffs) == 1
        assert orphan_diffs[0].kind == "removed"

    def test_discover_managed_ids_metadata_only_block(self) -> None:
        """Matcher with `__cpm_id` field but NO `hooks` key at all →
        discover finds it via the field."""
        doc = _doc_with_events(
            {"SessionStart": [{"matcher": "startup", "__cpm_id": "meta-only"}]}
        )
        discovered = discover_managed_ids(doc)
        assert len(discovered) == 1
        event, cpm_id, _ = discovered[0]
        assert event == "SessionStart"
        assert cpm_id == "meta-only"

    def test_discover_managed_ids_empty_desired_guard(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Empty desired + non-empty discovered → compute returns []
        with stderr warning. With mass_remove=True → returns removed diffs."""
        plugin = tmp_path / "empty_plugin"
        plugin.mkdir()  # no default-settings-hooks.yaml → desired == {}
        settings_data = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "__cpm_id": "orphan-1",
                        "hooks": [
                            {"command": "# cpm:orphan-1\nrun", "type": "command"}
                        ],
                    },
                    {
                        "matcher": "resume",
                        "__cpm_id": "orphan-2",
                        "hooks": [
                            {"command": "# cpm:orphan-2\nrun", "type": "command"}
                        ],
                    },
                ]
            }
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(settings_data))

        # Default: refuse mass-remove
        diffs = compute_settings_hooks_diff(settings, [plugin])
        assert diffs == []
        captured = capsys.readouterr()
        assert "refusing to mass-remove" in captured.err
        assert "2 managed entries" in captured.err

        # Explicit opt-in
        diffs_mass = compute_settings_hooks_diff(settings, [plugin], mass_remove=True)
        assert len(diffs_mass) == 2
        assert all(d.kind == "removed" for d in diffs_mass)
        assert {d.cpm_id for d in diffs_mass} == {"orphan-1", "orphan-2"}

    def test_discover_managed_ids_mid_line_comment_ignored(self) -> None:
        """`echo x  # cpm:foo` (mid-line) MUST NOT match the anchored regex."""
        doc = _doc_with_events(
            {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "hooks": [
                            {
                                "command": "echo x  # cpm:foo\necho done",
                                "type": "command",
                            }
                        ],
                    }
                ]
            }
        )
        discovered = discover_managed_ids(doc)
        assert discovered == []
        assert _extract_cpm_id_from_command("echo x  # cpm:foo\necho done") is None
        # sanity: line-anchored with only leading whitespace DOES match
        assert _extract_cpm_id_from_command("  # cpm:foo\n") == "foo"


# ---------------------------------------------------------------------------
# TestOrphanEndToEnd — integration + round-trip tests for orphan removal.
# ---------------------------------------------------------------------------


class TestOrphanEndToEnd:
    def test_settings_hooks_orphan_end_to_end(self, tmp_path: Path) -> None:
        """Seed settings.json with a managed matcher NOT in current plugin
        defaults, run compute, run apply with the removed diff, re-read the
        file, assert the orphan is removed but user-owned entries survive."""
        plugin = tmp_path / "p"
        _write_plugin_default(plugin, [_sample_entry("kept", matchers=["startup"])])
        settings_data = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "__cpm_id": "kept",
                        "hooks": [
                            {
                                "command": resolve_command_template(
                                    _sample_entry("kept", matchers=["startup"]),
                                    plugin,
                                ),
                                "type": "command",
                            }
                        ],
                    },
                    {
                        "matcher": "startup",
                        "__cpm_id": "orphan-me",
                        "hooks": [
                            {
                                "command": "# cpm:orphan-me\nrun orphan",
                                "type": "command",
                            }
                        ],
                    },
                    {
                        "matcher": "resume",
                        "hooks": [{"command": "user-owned-cmd", "type": "command"}],
                    },
                ]
            }
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(settings_data))

        diffs = compute_settings_hooks_diff(settings, [plugin])
        orphan_diffs = [d for d in diffs if d.cpm_id == "orphan-me"]
        assert len(orphan_diffs) == 1
        assert orphan_diffs[0].kind == "removed"

        apply_settings_hooks_diffs(
            settings, diffs, apply_ids=set(), remove_ids={"orphan-me"}
        )

        final = json.loads(settings.read_text())
        matchers = final["hooks"]["SessionStart"]
        # Orphan gone
        assert not any(m.get("__cpm_id") == "orphan-me" for m in matchers)
        # Managed `kept` survives
        assert any(m.get("__cpm_id") == "kept" for m in matchers)
        # User-owned `resume` matcher survives
        assert any(
            m.get("matcher") == "resume"
            and any(h.get("command") == "user-owned-cmd" for h in m.get("hooks", []))
            for m in matchers
        )

        # Round-trip: re-discover returns empty for orphan-me
        reread_doc = SettingsDocument.from_dict(settings, final)
        rediscovered_ids = {t[1] for t in discover_managed_ids(reread_doc)}
        assert "orphan-me" not in rediscovered_ids
        assert "kept" in rediscovered_ids

    def test_settings_hooks_apply_idempotent(self, tmp_path: Path) -> None:
        """Applying the same removed diff twice is a no-op on the second run."""
        plugin = tmp_path / "p"
        plugin.mkdir()  # empty → desired == {}
        settings_data = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "__cpm_id": "zombie",
                        "hooks": [
                            {
                                "command": "# cpm:zombie\nrun",
                                "type": "command",
                            }
                        ],
                    }
                ]
            }
        }
        settings = tmp_path / "settings.json"
        settings.write_text(json.dumps(settings_data))

        diffs = compute_settings_hooks_diff(settings, [plugin], mass_remove=True)
        assert len(diffs) == 1
        apply_settings_hooks_diffs(
            settings, diffs, apply_ids=set(), remove_ids={"zombie"}
        )
        after_first = json.loads(settings.read_text())
        assert not any(
            m.get("__cpm_id") == "zombie" for m in after_first["hooks"]["SessionStart"]
        )

        # Second apply — diffs list is empty now (nothing to discover), but
        # feeding the same diff again must be idempotent.
        apply_settings_hooks_diffs(
            settings, diffs, apply_ids=set(), remove_ids={"zombie"}
        )
        after_second = json.loads(settings.read_text())
        assert after_first == after_second


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


# ---------------------------------------------------------------------------
# TestVersionedSubdirFallback — tests for the versioned cache layout
# (plugin_dir/<version>/.claude-plugin/default-settings-hooks.yaml).
# ---------------------------------------------------------------------------


class TestVersionedSubdirFallback:
    def test_versioned_subdir_found_when_direct_lookup_misses(
        self, tmp_path: Path
    ) -> None:
        """Unversioned plugin_dir has no direct .claude-plugin/; file lives in 4.0.0/."""
        plugin = tmp_path / "proj"
        versioned = plugin / "4.0.0"
        _write_plugin_default(versioned, [_sample_entry("id-a")])
        merged = merge_settings_defaults([plugin])
        assert "id-a" in merged
        assert merged["id-a"]["_source_plugin_dir"] == str(versioned)

    def test_highest_semver_version_selected(self, tmp_path: Path) -> None:
        """With 3.0.1 and 4.0.0, 4.0.0 wins."""
        plugin = tmp_path / "proj"
        _write_plugin_default(plugin / "3.0.1", [_sample_entry("old-id")])
        _write_plugin_default(plugin / "4.0.0", [_sample_entry("new-id")])
        merged = merge_settings_defaults([plugin])
        assert "new-id" in merged
        assert "old-id" not in merged
        assert merged["new-id"]["_source_plugin_dir"] == str(plugin / "4.0.0")

    def test_nonversion_subdir_ignored_no_crash(self, tmp_path: Path) -> None:
        """_shared/ alongside 4.0.0/ is silently ignored; no InvalidVersion crash."""
        plugin = tmp_path / "proj"
        (plugin / "_shared" / ".claude-plugin").mkdir(parents=True)
        (
            plugin / "_shared" / ".claude-plugin" / "default-settings-hooks.yaml"
        ).write_text(yaml.safe_dump({"hooks": [_sample_entry("shared-id")]}))
        _write_plugin_default(plugin / "4.0.0", [_sample_entry("real-id")])
        merged = merge_settings_defaults([plugin])
        assert "real-id" in merged
        assert "shared-id" not in merged

    def test_no_versioned_subdir_returns_empty(self, tmp_path: Path) -> None:
        """plugin_dir with no versioned subdirs → empty merged dict (no crash)."""
        plugin = tmp_path / "proj"
        plugin.mkdir()
        merged = merge_settings_defaults([plugin])
        assert merged == {}

    def test_source_plugin_dir_present_in_direct_layout(self, tmp_path: Path) -> None:
        """Direct .claude-plugin/ layout also gets _source_plugin_dir set."""
        plugin = tmp_path / "p"
        _write_plugin_default(plugin, [_sample_entry("id-x")])
        merged = merge_settings_defaults([plugin])
        assert "_source_plugin_dir" in merged["id-x"]
        assert merged["id-x"]["_source_plugin_dir"] == str(plugin)

    def test_plugin_cache_dir_resolved_in_applied_command(self, tmp_path: Path) -> None:
        """{plugin_cache_dir} in command must resolve to the actual versioned dir."""
        plugin = tmp_path / "proj"
        versioned = plugin / "4.0.0"
        entry = _sample_entry(
            "session-hook",
            command="{python} {script} --cache {plugin_cache_dir}",
        )
        _write_plugin_default(versioned, [entry])

        settings = tmp_path / "settings.json"
        settings.write_text("{}")
        diffs = compute_settings_hooks_diff(settings, [plugin])
        assert len(diffs) == 1
        assert diffs[0].kind == "new"

        apply_settings_hooks_diffs(settings, diffs, apply_ids={"session-hook"})
        data = json.loads(settings.read_text())
        cmd = data["hooks"]["SessionStart"][0]["hooks"][0]["command"]
        # {plugin_cache_dir} must resolve to the versioned dir, not "."
        assert str(versioned) in cmd
        assert "{plugin_cache_dir}" not in cmd

    def test_unchanged_detection_with_versioned_subdir(self, tmp_path: Path) -> None:
        """If settings.json already has the hook with correct versioned path,
        compute reports 'unchanged' (not 'changed')."""
        plugin = tmp_path / "proj"
        versioned = plugin / "4.0.0"
        entry = _sample_entry(
            "v-hook",
            command="{python} {script} --cache {plugin_cache_dir}",
            matchers=["startup"],
        )
        _write_plugin_default(versioned, [entry])

        # Simulate already-applied state: command uses versioned dir
        resolved_cmd = resolve_command_template(entry, versioned)
        settings_data = {
            "hooks": {
                "SessionStart": [
                    {
                        "matcher": "startup",
                        "__cpm_id": "v-hook",
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
