"""Tests for installer.update — version comparison and display."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from installer.detect import InstallState
from installer.update import (
    _read_installed_version,
    _read_marketplace_versions,
    compare_versions,
    display_version_diff,
)


class TestReadMarketplaceVersions:
    def test_reads_versions(self, marketplace_json: Path):
        versions = _read_marketplace_versions(marketplace_json)
        assert versions["proj"] == "1.0.0"
        assert versions["sandbox"] == "0.2.0"

    def test_missing_file_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            _read_marketplace_versions(tmp_path / "nope.json")


class TestReadInstalledVersion:
    def test_reads_from_plugin_json(self, tmp_path: Path):
        plugin_dir = tmp_path / "proj"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text(json.dumps({"version": "0.9.0"}))
        assert _read_installed_version(tmp_path, "proj") == "0.9.0"

    def test_reads_from_claude_plugin_subdir(self, tmp_path: Path):
        plugin_dir = tmp_path / "proj" / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(json.dumps({"version": "0.8.0"}))
        assert _read_installed_version(tmp_path, "proj") == "0.8.0"

    def test_missing_plugin(self, tmp_path: Path):
        assert _read_installed_version(tmp_path, "nonexistent") is None

    def test_malformed_json(self, tmp_path: Path):
        plugin_dir = tmp_path / "proj"
        plugin_dir.mkdir()
        (plugin_dir / "plugin.json").write_text("not json")
        assert _read_installed_version(tmp_path, "proj") is None


class TestCompareVersions:
    def test_detects_diff(self, tmp_path: Path, marketplace_json: Path):
        cache = tmp_path / "cache"
        plugin_dir = cache / "proj"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(json.dumps({"version": "0.9.0"}))

        state = InstallState(
            cache_dir=cache,
            installed_plugins=["proj"],
        )
        diffs = compare_versions(state, marketplace_json)
        assert "proj" in diffs
        assert diffs["proj"] == ("0.9.0", "1.0.0")

    def test_no_diff_when_same(self, tmp_path: Path, marketplace_json: Path):
        cache = tmp_path / "cache"
        plugin_dir = cache / "proj"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(json.dumps({"version": "1.0.0"}))

        state = InstallState(
            cache_dir=cache,
            installed_plugins=["proj"],
        )
        diffs = compare_versions(state, marketplace_json)
        assert "proj" not in diffs

    def test_no_cache_dir(self, marketplace_json: Path):
        state = InstallState(cache_dir=None)
        assert compare_versions(state, marketplace_json) == {}


class TestDisplayVersionDiff:
    def test_no_diffs(self, mock_console):
        display_version_diff({}, mock_console)
        # Should print "up to date"

    def test_with_diffs(self, mock_console):
        display_version_diff({"proj": ("0.9.0", "1.0.0")}, mock_console)
        # Should not raise
