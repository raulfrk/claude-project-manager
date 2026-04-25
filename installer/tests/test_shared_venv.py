"""Tests for installer.shared_venv — shared marketplace venv creation."""

from __future__ import annotations

import subprocess
from unittest.mock import MagicMock, patch


class TestEnsureSharedVenv:
    @patch("installer.shared_venv.subprocess.run")
    def test_happy_path_invokes_uv_sync_in_marketplace_dir(self, mock_run, tmp_path):
        """ensure_shared_venv runs `uv sync --frozen --extra plugins` in marketplace_dir."""
        from installer.shared_venv import ensure_shared_venv

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        ensure_shared_venv(tmp_path)

        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        cmd = args[0]
        assert cmd[0] == "uv"
        assert "sync" in cmd
        assert "--frozen" in cmd
        assert "--extra" in cmd
        assert "plugins" in cmd
        # Must run in the marketplace dir (either via cwd= or --directory=)
        used_cwd = kwargs.get("cwd") == tmp_path
        used_directory_flag = "--directory" in cmd and cmd[
            cmd.index("--directory") + 1
        ] == str(tmp_path)
        assert used_cwd or used_directory_flag, (
            f"Expected cwd={tmp_path} or --directory={tmp_path}; got cmd={cmd}, kwargs={kwargs}"
        )
        # stdin=DEVNULL mirrors plugin_cli._run for TTY safety
        assert kwargs.get("stdin") == subprocess.DEVNULL
