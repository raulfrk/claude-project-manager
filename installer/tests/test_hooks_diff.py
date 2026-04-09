"""Tests for installer.hooks_diff — diff engine for default-hooks.yaml."""

from __future__ import annotations

from pathlib import Path

import yaml

from installer.hooks_diff import (
    HookDiff,
    apply_diffs,
    compute_hooks_diff,
    merge_defaults,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_default_hooks(plugin_dir: Path, data: dict, subdir: bool = False) -> None:
    """Write a default-hooks.yaml into a plugin directory."""
    if subdir:
        target = plugin_dir / ".claude-plugin"
        target.mkdir(parents=True, exist_ok=True)
        (target / "default-hooks.yaml").write_text(
            yaml.dump(data, default_flow_style=False)
        )
    else:
        plugin_dir.mkdir(parents=True, exist_ok=True)
        (plugin_dir / "default-hooks.yaml").write_text(
            yaml.dump(data, default_flow_style=False)
        )


def _write_hooks_yaml(path: Path, data: dict) -> None:
    """Write a hooks.yaml file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump(data, default_flow_style=False))


def _make_hook(hook_id: str, **extra: object) -> dict:
    """Build a minimal hook dict."""
    return {"id": hook_id, "trigger_tool": f"tool_{hook_id}", **extra}


# ---------------------------------------------------------------------------
# merge_defaults
# ---------------------------------------------------------------------------


class TestMergeDefaults:
    def test_single_plugin_dir(self, tmp_path: Path) -> None:
        """1. Single plugin dir with default-hooks.yaml returns merged dict."""
        plugin = tmp_path / "pluginA"
        _write_default_hooks(
            plugin,
            {
                "settings": {"max_depth": 3},
                "servers": {"srv1": "unix:///tmp/s1.sock"},
                "hooks": [_make_hook("h1"), _make_hook("h2")],
            },
        )

        result = merge_defaults([plugin])

        assert result["settings"] == {"max_depth": 3}
        assert result["servers"] == {"srv1": "unix:///tmp/s1.sock"}
        assert set(result["hooks"]) == {"h1", "h2"}

    def test_two_plugin_dirs_last_wins(self, tmp_path: Path) -> None:
        """2. Two plugin dirs — hooks merged, last wins on duplicate."""
        p1 = tmp_path / "p1"
        p2 = tmp_path / "p2"
        _write_default_hooks(
            p1,
            {
                "hooks": [_make_hook("shared", blocking=True)],
                "servers": {"s1": "addr1"},
            },
        )
        _write_default_hooks(
            p2,
            {
                "hooks": [_make_hook("shared", blocking=False), _make_hook("unique")],
                "servers": {"s2": "addr2"},
            },
        )

        result = merge_defaults([p1, p2])

        # Last wins for duplicate hook
        assert result["hooks"]["shared"]["blocking"] is False
        assert "unique" in result["hooks"]
        # Servers merged
        assert result["servers"]["s1"] == "addr1"
        assert result["servers"]["s2"] == "addr2"

    def test_missing_default_hooks_skipped(self, tmp_path: Path) -> None:
        """3. Missing default-hooks.yaml is skipped silently."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        result = merge_defaults([empty_dir])

        assert result["hooks"] == {}
        assert result["settings"] == {}
        assert result["servers"] == {}

    def test_claude_plugin_subdir(self, tmp_path: Path) -> None:
        """3b. default-hooks.yaml found inside .claude-plugin/ subdir."""
        plugin = tmp_path / "pluginB"
        _write_default_hooks(
            plugin,
            {
                "hooks": [_make_hook("sub_h")],
                "servers": {"sub_srv": "unix:///tmp/sub.sock"},
            },
            subdir=True,
        )

        result = merge_defaults([plugin])

        assert "sub_h" in result["hooks"]
        assert result["servers"]["sub_srv"] == "unix:///tmp/sub.sock"

    def test_malformed_yaml_skipped(self, tmp_path: Path, caplog: object) -> None:
        """4. Malformed YAML is skipped with warning."""
        plugin = tmp_path / "bad"
        plugin.mkdir()
        (plugin / "default-hooks.yaml").write_text(": : :\n  - [invalid")

        result = merge_defaults([plugin])
        assert result["hooks"] == {}


# ---------------------------------------------------------------------------
# compute_hooks_diff
# ---------------------------------------------------------------------------


class TestComputeHooksDiff:
    def test_no_current_all_new(self, tmp_path: Path) -> None:
        """5. No current hooks.yaml, defaults exist — all hooks are 'new'."""
        plugin = tmp_path / "plugin"
        _write_default_hooks(plugin, {"hooks": [_make_hook("a"), _make_hook("b")]})

        diffs = compute_hooks_diff(tmp_path / "hooks.yaml", [plugin])

        assert len(diffs) == 2
        ids = {d.hook_id for d in diffs}
        assert ids == {"a", "b"}
        assert all(d.status == "new" for d in diffs)
        assert all(d.current_yaml is None for d in diffs)
        assert all(d.proposed_yaml is not None for d in diffs)

    def test_current_matches_defaults_empty_diff(self, tmp_path: Path) -> None:
        """6. Current matches defaults — empty diff list."""
        hook = _make_hook("h1")
        plugin = tmp_path / "plugin"
        _write_default_hooks(plugin, {"hooks": [hook]})
        _write_hooks_yaml(tmp_path / "hooks.yaml", {"hooks": [hook]})

        diffs = compute_hooks_diff(tmp_path / "hooks.yaml", [plugin])

        assert diffs == []

    def test_changed_hook_detected(self, tmp_path: Path) -> None:
        """7. Current has hook with different content — 'changed' diff."""
        plugin = tmp_path / "plugin"
        _write_default_hooks(
            plugin,
            {
                "hooks": [_make_hook("h1", blocking=True)],
            },
        )
        _write_hooks_yaml(
            tmp_path / "hooks.yaml",
            {
                "hooks": [_make_hook("h1", blocking=False)],
            },
        )

        diffs = compute_hooks_diff(tmp_path / "hooks.yaml", [plugin])

        assert len(diffs) == 1
        assert diffs[0].hook_id == "h1"
        assert diffs[0].status == "changed"
        assert diffs[0].current_yaml is not None
        assert diffs[0].proposed_yaml is not None
        assert diffs[0].unified_diff != ""

    def test_removed_hook_via_source_marker(self, tmp_path: Path) -> None:
        """8. Defaults removed a hook — 'removed' diff (source marker)."""
        plugin = tmp_path / "plugin"
        # Defaults have no hooks now
        _write_default_hooks(plugin, {"hooks": []})
        # Current has a hook that was originally from defaults
        _write_hooks_yaml(
            tmp_path / "hooks.yaml",
            {
                "hooks": [_make_hook("old_hook", source="default:plugin")],
            },
        )

        diffs = compute_hooks_diff(tmp_path / "hooks.yaml", [plugin])

        assert len(diffs) == 1
        assert diffs[0].hook_id == "old_hook"
        assert diffs[0].status == "removed"
        assert diffs[0].proposed_yaml is None

    def test_custom_hook_excluded(self, tmp_path: Path) -> None:
        """9. Current has custom hook (not in defaults) — excluded from diffs."""
        plugin = tmp_path / "plugin"
        _write_default_hooks(plugin, {"hooks": [_make_hook("default_h")]})
        _write_hooks_yaml(
            tmp_path / "hooks.yaml",
            {
                "hooks": [_make_hook("default_h"), _make_hook("custom_h")],
            },
        )

        diffs = compute_hooks_diff(tmp_path / "hooks.yaml", [plugin])

        # default_h matches, custom_h excluded — empty
        assert diffs == []


# ---------------------------------------------------------------------------
# apply_diffs
# ---------------------------------------------------------------------------


class TestApplyDiffs:
    def test_apply_new_hooks(self, tmp_path: Path) -> None:
        """10. Apply new hooks — added to hooks.yaml."""
        hooks_path = tmp_path / "hooks.yaml"
        _write_hooks_yaml(hooks_path, {"hooks": []})

        new_hook = _make_hook("new1")
        diff = HookDiff(
            hook_id="new1",
            status="new",
            current_yaml=None,
            proposed_yaml=yaml.dump(new_hook, default_flow_style=False),
            unified_diff="",
        )

        apply_diffs(hooks_path, [diff], apply_ids={"new1"}, remove_ids=set())

        result = yaml.safe_load(hooks_path.read_text())
        hook_ids = [h["id"] for h in result["hooks"]]
        assert "new1" in hook_ids

    def test_apply_changed_hooks(self, tmp_path: Path) -> None:
        """11. Apply changed hooks — replaced in hooks.yaml."""
        hooks_path = tmp_path / "hooks.yaml"
        _write_hooks_yaml(
            hooks_path,
            {
                "hooks": [_make_hook("h1", blocking=False)],
            },
        )

        updated = _make_hook("h1", blocking=True)
        diff = HookDiff(
            hook_id="h1",
            status="changed",
            current_yaml=yaml.dump(_make_hook("h1", blocking=False)),
            proposed_yaml=yaml.dump(updated, default_flow_style=False),
            unified_diff="",
        )

        apply_diffs(hooks_path, [diff], apply_ids={"h1"}, remove_ids=set())

        result = yaml.safe_load(hooks_path.read_text())
        h1 = next(h for h in result["hooks"] if h["id"] == "h1")
        assert h1["blocking"] is True

    def test_remove_hooks(self, tmp_path: Path) -> None:
        """12. Remove hooks — deleted from hooks.yaml."""
        hooks_path = tmp_path / "hooks.yaml"
        _write_hooks_yaml(
            hooks_path,
            {
                "hooks": [_make_hook("h1"), _make_hook("h2")],
            },
        )

        diff = HookDiff(
            hook_id="h1",
            status="removed",
            current_yaml=yaml.dump(_make_hook("h1")),
            proposed_yaml=None,
            unified_diff="",
        )

        apply_diffs(hooks_path, [diff], apply_ids=set(), remove_ids={"h1"})

        result = yaml.safe_load(hooks_path.read_text())
        hook_ids = [h["id"] for h in result["hooks"]]
        assert "h1" not in hook_ids
        assert "h2" in hook_ids

    def test_skip_not_in_apply_ids(self, tmp_path: Path) -> None:
        """13. Skip (not in apply_ids) — unchanged in hooks.yaml."""
        hooks_path = tmp_path / "hooks.yaml"
        _write_hooks_yaml(
            hooks_path,
            {
                "hooks": [_make_hook("h1", blocking=False)],
            },
        )

        updated = _make_hook("h1", blocking=True)
        diff = HookDiff(
            hook_id="h1",
            status="changed",
            current_yaml=yaml.dump(_make_hook("h1", blocking=False)),
            proposed_yaml=yaml.dump(updated, default_flow_style=False),
            unified_diff="",
        )

        # h1 NOT in apply_ids — should be unchanged
        apply_diffs(hooks_path, [diff], apply_ids=set(), remove_ids=set())

        result = yaml.safe_load(hooks_path.read_text())
        h1 = next(h for h in result["hooks"] if h["id"] == "h1")
        assert h1["blocking"] is False


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_hooks_yaml_treated_as_missing(self, tmp_path: Path) -> None:
        """14. Empty hooks.yaml file — treated as missing (all new)."""
        hooks_path = tmp_path / "hooks.yaml"
        hooks_path.write_text("")

        plugin = tmp_path / "plugin"
        _write_default_hooks(plugin, {"hooks": [_make_hook("x")]})

        diffs = compute_hooks_diff(hooks_path, [plugin])

        assert len(diffs) == 1
        assert diffs[0].status == "new"
        assert diffs[0].hook_id == "x"

    def test_only_custom_hooks_empty_diff(self, tmp_path: Path) -> None:
        """15. hooks.yaml with only custom hooks — empty diff."""
        hooks_path = tmp_path / "hooks.yaml"
        _write_hooks_yaml(
            hooks_path,
            {
                "hooks": [_make_hook("my_custom")],
            },
        )

        plugin = tmp_path / "plugin"
        # Defaults have nothing
        _write_default_hooks(plugin, {"hooks": []})

        diffs = compute_hooks_diff(hooks_path, [plugin])

        assert diffs == []
