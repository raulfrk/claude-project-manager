"""Tests for installer.update — version comparison and update/reinstall."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from installer.detect import InstallState
from installer.errors import InstallerError
from installer.update import (
    _read_installed_version,
    _read_marketplace_versions,
    compare_versions,
    display_version_diff,
    run_reinstall,
    run_update,
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


class TestRunUpdate:
    def test_no_cache_dir_raises(self, mock_console):
        state = InstallState(cache_dir=None)
        with pytest.raises(InstallerError, match="No cache directory"):
            run_update(["proj"], state, mock_console)

    def test_successful_update(self, tmp_path: Path, mock_home: Path, mock_console):
        cache = tmp_path / "cache"
        (cache / "proj").mkdir(parents=True)
        (cache / "proj" / "old.txt").write_text("old")

        state = InstallState(cache_dir=cache, installed_plugins=["proj"])

        # Create a fake source dir
        source = tmp_path / "plugins" / "proj"
        source.mkdir(parents=True)
        (source / "new.txt").write_text("new")

        with patch("installer.update._resolve_plugin_source", return_value=source):
            results = run_update(["proj"], state, mock_console)

        assert results["proj"] is True
        assert (cache / "proj" / "new.txt").exists()

    def test_missing_source_fails(self, tmp_path: Path, mock_home: Path, mock_console):
        cache = tmp_path / "cache"
        (cache / "proj").mkdir(parents=True)
        state = InstallState(cache_dir=cache, installed_plugins=["proj"])

        with patch(
            "installer.update._resolve_plugin_source",
            return_value=tmp_path / "nonexistent",
        ):
            results = run_update(["proj"], state, mock_console)

        assert results["proj"] is False


class TestRunReinstall:
    def test_no_cache_dir_raises(self, mock_console):
        state = InstallState(cache_dir=None)
        with pytest.raises(InstallerError, match="No cache directory"):
            run_reinstall(["proj"], state, mock_console)

    def test_reinstall_keep_configs(
        self, tmp_path: Path, mock_home: Path, mock_console
    ):
        cache = tmp_path / "cache"
        (cache / "proj").mkdir(parents=True)

        state = InstallState(cache_dir=cache, installed_plugins=["proj"])

        source = tmp_path / "plugins" / "proj"
        source.mkdir(parents=True)
        (source / "plugin.json").write_text("{}")

        with (
            patch("installer.update.Prompt.ask", return_value="1"),  # keep configs
            patch("installer.update._resolve_plugin_source", return_value=source),
        ):
            results = run_reinstall(["proj"], state, mock_console)

        assert results["proj"] is True
