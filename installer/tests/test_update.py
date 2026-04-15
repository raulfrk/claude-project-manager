"""Tests for installer.update — version comparison utilities."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from installer.update import _read_installed_version

_PATCH_VERSIONS = "installer.update.get_installed_plugin_versions"


class TestReadInstalledVersion:
    def test_cli_primary(self, tmp_path: Path):
        with patch(_PATCH_VERSIONS, return_value={"proj": "4.0.0"}):
            assert _read_installed_version(tmp_path, "proj") == "4.0.0"

    def test_cli_empty_disk_fallback(self, tmp_path: Path):
        plugin_dir = tmp_path / "proj" / "4.0.0" / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(json.dumps({"version": "4.0.0"}))

        with patch(_PATCH_VERSIONS, return_value={}):
            assert _read_installed_version(tmp_path, "proj") == "4.0.0"

    def test_cli_exception_disk_fallback(self, tmp_path: Path):
        plugin_dir = tmp_path / "proj" / "3.0.0" / ".claude-plugin"
        plugin_dir.mkdir(parents=True)
        (plugin_dir / "plugin.json").write_text(json.dumps({"version": "3.0.0"}))

        with patch(_PATCH_VERSIONS, side_effect=Exception("CLI unavailable")):
            assert _read_installed_version(tmp_path, "proj") == "3.0.0"

    def test_both_fail_returns_none(self, tmp_path: Path):
        with patch(_PATCH_VERSIONS, return_value={}):
            assert _read_installed_version(tmp_path, "proj") is None

    def test_disk_fallback_picks_latest_version_dir(self, tmp_path: Path):
        for ver in ("1.0.0", "2.0.0"):
            d = tmp_path / "proj" / ver / ".claude-plugin"
            d.mkdir(parents=True)
            (d / "plugin.json").write_text(json.dumps({"version": ver}))

        with patch(_PATCH_VERSIONS, return_value={}):
            assert _read_installed_version(tmp_path, "proj") == "2.0.0"

    def test_disk_fallback_skips_dotdirs(self, tmp_path: Path):
        hidden = tmp_path / "proj" / ".tmp"
        hidden.mkdir(parents=True)
        real = tmp_path / "proj" / "1.0.0" / ".claude-plugin"
        real.mkdir(parents=True)
        (real / "plugin.json").write_text(json.dumps({"version": "1.0.0"}))

        with patch(_PATCH_VERSIONS, return_value={}):
            assert _read_installed_version(tmp_path, "proj") == "1.0.0"

    def test_disk_fallback_plain_plugin_json(self, tmp_path: Path):
        """Fallback also checks plugin.json directly in version dir."""
        d = tmp_path / "proj" / "1.0.0"
        d.mkdir(parents=True)
        (d / "plugin.json").write_text(json.dumps({"version": "1.0.0"}))

        with patch(_PATCH_VERSIONS, return_value={}):
            assert _read_installed_version(tmp_path, "proj") == "1.0.0"
