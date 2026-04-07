"""Tests for installer.uninstall — plugin removal and cleanup."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from installer.detect import InstallState
from installer.errors import UserCancelled
from installer.uninstall import cleanup_config_files, remove_plugins, run_uninstall


class TestRemovePlugins:
    def test_removes_existing_plugin(self, tmp_path: Path, mock_console):
        cache = tmp_path / "cache"
        (cache / "proj").mkdir(parents=True)
        (cache / "proj" / "plugin.json").write_text("{}")

        state = InstallState(cache_dir=cache)
        results = remove_plugins(["proj"], state, mock_console)
        assert results == {"proj": True}
        assert not (cache / "proj").exists()

    def test_skips_missing_plugin(self, tmp_path: Path, mock_console):
        cache = tmp_path / "cache"
        cache.mkdir()
        state = InstallState(cache_dir=cache)
        results = remove_plugins(["nonexistent"], state, mock_console)
        assert results == {"nonexistent": True}

    def test_handles_no_cache_dir(self, mock_console):
        state = InstallState(cache_dir=None)
        results = remove_plugins(["proj"], state, mock_console)
        assert results == {"proj": True}

    def test_handles_permission_error(self, tmp_path: Path, mock_console):
        cache = tmp_path / "cache"
        (cache / "proj").mkdir(parents=True)
        state = InstallState(cache_dir=cache)

        with patch(
            "installer.uninstall.shutil.rmtree", side_effect=PermissionError("denied")
        ):
            results = remove_plugins(["proj"], state, mock_console)
        assert results == {"proj": False}

    def test_multiple_plugins(self, tmp_path: Path, mock_console):
        cache = tmp_path / "cache"
        (cache / "proj").mkdir(parents=True)
        (cache / "sandbox").mkdir(parents=True)
        state = InstallState(cache_dir=cache)
        results = remove_plugins(["proj", "sandbox"], state, mock_console)
        assert results == {"proj": True, "sandbox": True}


class TestCleanupConfigFiles:
    def test_removes_existing_configs(self, mock_home: Path, mock_console):
        (mock_home / ".claude" / "proj.yaml").write_text("v: 1\n")
        (mock_home / ".claude" / "worktree.yaml").write_text("v: 1\n")
        cleanup_config_files(mock_console)
        assert not (mock_home / ".claude" / "proj.yaml").exists()
        assert not (mock_home / ".claude" / "worktree.yaml").exists()

    def test_handles_missing_configs(self, mock_home: Path, mock_console):
        """Does not raise when configs don't exist."""
        cleanup_config_files(mock_console)


class TestRunUninstall:
    def test_nothing_to_uninstall(self, mock_home: Path, mock_console):
        """When no plugins installed, prints message and returns."""
        run_uninstall(full_cleanup=False, console=mock_console)

    def test_user_cancels(self, mock_home: Path, mock_console):
        cache = mock_home / ".claude" / "plugins" / "cache" / "claude-project-manager"
        (cache / "proj").mkdir(parents=True)

        with (
            patch("installer.uninstall.Confirm.ask", return_value=False),
            pytest.raises(UserCancelled),
        ):
            run_uninstall(full_cleanup=False, console=mock_console)

    def test_uninstall_removes_plugins(self, mock_home: Path, mock_console):
        cache = mock_home / ".claude" / "plugins" / "cache" / "claude-project-manager"
        (cache / "proj").mkdir(parents=True)
        (cache / "proj" / "plugin.json").write_text("{}")

        with patch("installer.uninstall.Confirm.ask", return_value=True):
            run_uninstall(full_cleanup=False, console=mock_console)

        assert not (cache / "proj").exists()

    def test_full_cleanup_removes_configs(self, mock_home: Path, mock_console):
        cache = mock_home / ".claude" / "plugins" / "cache" / "claude-project-manager"
        (cache / "proj").mkdir(parents=True)
        (mock_home / ".claude" / "proj.yaml").write_text("v: 1\n")

        with patch("installer.uninstall.Confirm.ask", return_value=True):
            run_uninstall(full_cleanup=True, console=mock_console)

        assert not (mock_home / ".claude" / "proj.yaml").exists()
