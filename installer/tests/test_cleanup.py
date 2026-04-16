"""Tests for installer.cleanup orphan plugin cache pruning."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest

from installer.cleanup import (
    PruneReport,
    _parse_live_plugins,
    cleanup_orphaned_plugin_caches,
    prune_orphaned_plugins,
    prune_stale_versions,
    scan_stale_cache,
)


def _write_installed_json(path: Path, plugins: dict[str, Any]) -> None:
    path.write_text(json.dumps({"version": 2, "plugins": plugins}))


def _make_plugin_dir(
    cache_root: Path, marketplace: str, plugin: str, version: str = "1.0.0"
) -> Path:
    p = cache_root / marketplace / plugin / version
    p.mkdir(parents=True)
    (p / "plugin.json").write_text("{}")
    return p


def test_prune_removes_stale_dirs(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _make_plugin_dir(cache_root, "claude-project-manager", "proj")
    _make_plugin_dir(cache_root, "claude-project-manager", "orphan")
    installed = tmp_path / "installed_plugins.json"
    _write_installed_json(
        installed,
        {"proj@claude-project-manager": [{"version": "1.0.0"}]},
    )

    removed = cleanup_orphaned_plugin_caches(cache_root, installed)

    assert removed == ["claude-project-manager/orphan"]
    assert not (cache_root / "claude-project-manager" / "orphan").exists()
    assert (cache_root / "claude-project-manager" / "proj").exists()


def test_prune_preserves_live_plugin_versions(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    router_dir = cache_root / "claude-project-manager" / "router"
    (router_dir / "2.0.0").mkdir(parents=True)
    (router_dir / "2.1.0").mkdir(parents=True)
    installed = tmp_path / "installed_plugins.json"
    _write_installed_json(
        installed,
        {"router@claude-project-manager": [{"version": "2.1.0"}]},
    )

    removed = cleanup_orphaned_plugin_caches(cache_root, installed)

    assert removed == []
    assert (router_dir / "2.0.0").exists()
    assert (router_dir / "2.1.0").exists()


def test_prune_missing_installed_json_returns_empty(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _make_plugin_dir(cache_root, "mp", "foo")
    installed = tmp_path / "nope.json"

    removed = cleanup_orphaned_plugin_caches(cache_root, installed)

    assert removed == []
    assert (cache_root / "mp" / "foo").exists()


def test_prune_invalid_json_returns_empty(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _make_plugin_dir(cache_root, "mp", "foo")
    installed = tmp_path / "installed_plugins.json"
    installed.write_text("{not valid json")

    with caplog.at_level(logging.WARNING, logger="installer"):
        removed = cleanup_orphaned_plugin_caches(cache_root, installed)

    assert removed == []
    assert (cache_root / "mp" / "foo").exists()
    assert any("failed to parse" in r.message for r in caplog.records)


def test_prune_dry_run_preserves_files(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _make_plugin_dir(cache_root, "mp", "orphan")
    installed = tmp_path / "installed_plugins.json"
    _write_installed_json(installed, {})

    removed = cleanup_orphaned_plugin_caches(cache_root, installed, dry_run=True)

    assert removed == ["mp/orphan"]
    assert (cache_root / "mp" / "orphan").exists()


def test_prune_interactive_confirm_false_preserves(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _make_plugin_dir(cache_root, "mp", "orphan")
    installed = tmp_path / "installed_plugins.json"
    _write_installed_json(installed, {})

    def confirm(_names: list[str]) -> bool:
        return False

    removed = cleanup_orphaned_plugin_caches(
        cache_root, installed, interactive=True, confirm=confirm
    )

    assert removed == []
    assert (cache_root / "mp" / "orphan").exists()


def test_prune_interactive_confirm_true_removes(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _make_plugin_dir(cache_root, "mp", "orphan")
    installed = tmp_path / "installed_plugins.json"
    _write_installed_json(installed, {})
    seen: list[list[str]] = []

    def confirm(names: list[str]) -> bool:
        seen.append(names)
        return True

    removed = cleanup_orphaned_plugin_caches(
        cache_root, installed, interactive=True, confirm=confirm
    )

    assert removed == ["mp/orphan"]
    assert seen == [["mp/orphan"]]
    assert not (cache_root / "mp" / "orphan").exists()


def test_prune_empty_cache_returns_empty(tmp_path: Path) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    installed = tmp_path / "installed_plugins.json"
    _write_installed_json(installed, {})

    removed = cleanup_orphaned_plugin_caches(cache_root, installed)

    assert removed == []


def test_prune_symlink_orphan_unlinked_not_recursed(tmp_path: Path) -> None:
    """A symlink to a live sibling dir is unlinked, not recursed into."""
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    marketplace_dir = cache_root / "mp"
    marketplace_dir.mkdir()
    live_target = marketplace_dir / "live"
    live_target.mkdir()
    (live_target / "important.txt").write_text("keep me")
    link = marketplace_dir / "orphan"
    link.symlink_to(live_target)
    installed = tmp_path / "installed_plugins.json"
    _write_installed_json(installed, {"live@mp": [{"version": "1.0.0"}]})

    removed = cleanup_orphaned_plugin_caches(cache_root, installed)

    assert removed == ["mp/orphan"]
    assert not link.is_symlink()
    assert not link.exists()
    assert live_target.exists()
    assert (live_target / "important.txt").exists()


def test_prune_path_containment_rejects_escape(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    marketplace_dir = cache_root / "mp"
    marketplace_dir.mkdir()
    outside = tmp_path / "outside_target"
    outside.mkdir()
    orphan = marketplace_dir / "orphan"
    orphan.mkdir()
    installed = tmp_path / "installed_plugins.json"
    _write_installed_json(installed, {})

    real_resolve = Path.resolve
    cache_root_real = cache_root.resolve()

    def fake_resolve(self: Path, strict: bool = False) -> Path:
        if self == orphan:
            return outside.resolve()
        return real_resolve(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", fake_resolve)

    with caplog.at_level(logging.WARNING, logger="installer"):
        removed = cleanup_orphaned_plugin_caches(cache_root, installed)

    assert removed == []
    assert orphan.exists()
    assert any("escapes cache_root" in r.message for r in caplog.records)
    _ = cache_root_real


def test_prune_permission_error_logs_and_continues(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    import shutil as _shutil

    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    _make_plugin_dir(cache_root, "mp", "a_orphan")
    _make_plugin_dir(cache_root, "mp", "b_orphan")
    installed = tmp_path / "installed_plugins.json"
    _write_installed_json(installed, {})

    original_rmtree = _shutil.rmtree
    calls: list[Path] = []

    def fake_rmtree(path: Any, *args: Any, **kwargs: Any) -> None:
        p = Path(path)
        calls.append(p)
        if p.name == "a_orphan":
            raise PermissionError("nope")
        original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr("installer.cleanup.shutil.rmtree", fake_rmtree)

    with caplog.at_level(logging.WARNING, logger="installer"):
        removed = cleanup_orphaned_plugin_caches(cache_root, installed)

    assert removed == ["mp/b_orphan"]
    assert len(calls) == 2
    assert any("failed to remove" in r.message for r in caplog.records)


def _write_marketplace(tmp_path: Path, plugin_names: list[str]) -> Path:
    mp = tmp_path / "marketplace.json"
    mp.write_text(
        json.dumps({"plugins": [{"name": n, "version": "5.0.0"} for n in plugin_names]})
    )
    return mp


def _make_cache_dir(tmp_path: Path, plugin: str, version: str) -> Path:
    d = tmp_path / plugin / version
    d.mkdir(parents=True)
    return d


class TestScanStaleCache:
    def test_detects_orphan(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        _make_cache_dir(cache, "sandbox", "1.0.0")
        _make_cache_dir(cache, "proj", "5.0.0")
        mp = _write_marketplace(tmp_path, ["proj"])

        report = scan_stale_cache(cache, mp)

        assert report.orphans == ["sandbox"]
        assert report.stale_versions == {}

    def test_detects_stale_versions(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        for v in ("3.0.0", "4.0.0", "5.0.0"):
            _make_cache_dir(cache, "proj", v)
        mp = _write_marketplace(tmp_path, ["proj"])

        report = scan_stale_cache(cache, mp)

        assert report.orphans == []
        assert set(report.stale_versions["proj"]) == {"3.0.0", "4.0.0"}

    def test_ignores_current_version(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        _make_cache_dir(cache, "proj", "5.0.0")
        mp = _write_marketplace(tmp_path, ["proj"])

        report = scan_stale_cache(cache, mp)

        assert report.orphans == []
        assert report.stale_versions == {}

    def test_unparseable_version_skipped(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        _make_cache_dir(cache, "proj", "92f892f2b997")
        _make_cache_dir(cache, "proj", "5.0.0")
        mp = _write_marketplace(tmp_path, ["proj"])

        report = scan_stale_cache(cache, mp)

        assert (
            "proj" not in report.stale_versions
            or "92f892f2b997" not in report.stale_versions.get("proj", [])
        )

    def test_missing_marketplace_json(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        _make_cache_dir(cache, "proj", "5.0.0")

        with pytest.raises(FileNotFoundError):
            scan_stale_cache(cache, tmp_path / "nonexistent.json")

    def test_ignores_shared_dir(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "_shared").mkdir()
        _make_cache_dir(cache, "proj", "5.0.0")
        mp = _write_marketplace(tmp_path, ["proj"])

        report = scan_stale_cache(cache, mp)

        assert "_shared" not in report.orphans


class TestPruneStaleVersions:
    def test_removes_old_versions_keeps_newest(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        for v in ("3.0.0", "4.0.0", "5.0.0"):
            _make_cache_dir(cache, "proj", v)

        report = PruneReport(orphans=[], stale_versions={"proj": ["3.0.0", "4.0.0"]})
        deleted = prune_stale_versions(cache, report)

        assert (cache / "proj" / "5.0.0").is_dir()
        assert not (cache / "proj" / "3.0.0").exists()
        assert not (cache / "proj" / "4.0.0").exists()
        assert len(deleted) == 2

    def test_empty_report_noop(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        _make_cache_dir(cache, "proj", "5.0.0")

        report = PruneReport(orphans=[], stale_versions={})
        deleted = prune_stale_versions(cache, report)

        assert deleted == []
        assert (cache / "proj" / "5.0.0").is_dir()


class TestPruneOrphanedPlugins:
    def test_removes_listed_orphans(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "sandbox" / "1.0.0").mkdir(parents=True)
        (cache / "zoxide" / "1.0.0").mkdir(parents=True)
        (cache / "proj" / "5.0.0").mkdir(parents=True)

        deleted = prune_orphaned_plugins(cache, ["sandbox", "zoxide"])

        assert set(deleted) == {str(cache / "sandbox"), str(cache / "zoxide")}
        assert not (cache / "sandbox").exists()
        assert not (cache / "zoxide").exists()
        assert (cache / "proj").is_dir()

    def test_handles_missing_dir(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        deleted = prune_orphaned_plugins(cache, ["nonexistent"])
        assert deleted == []

    def test_empty_list_noop(self, tmp_path):
        cache = tmp_path / "cache"
        cache.mkdir()
        (cache / "proj" / "5.0.0").mkdir(parents=True)
        deleted = prune_orphaned_plugins(cache, [])
        assert deleted == []
        assert (cache / "proj").is_dir()


def test_parse_live_plugins_shape() -> None:
    data = {
        "plugins": {
            "router@claude-project-manager": [{"version": "2.1.0"}],
            "proj@claude-project-manager": [{"version": "4.0.0"}],
            "voicemode@voicemode": [{"version": "8.4.0p0"}],
            "malformed-no-at-sign": [],
        }
    }

    result = _parse_live_plugins(data)

    assert result == {
        "claude-project-manager": {"router", "proj"},
        "voicemode": {"voicemode"},
    }
