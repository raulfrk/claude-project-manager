"""Tests for installer.local_marketplace — local clone management."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from installer.errors import InstallerError


class TestConstants:
    def test_local_clone_dir_is_user_cache(self):
        from installer.local_marketplace import LOCAL_CLONE_DIR

        assert (
            LOCAL_CLONE_DIR
            == Path.home() / ".cache" / "claude-project-manager" / "local-marketplace"
        )

    def test_https_source_is_github_https_url(self):
        from installer.local_marketplace import _HTTPS_SOURCE

        assert _HTTPS_SOURCE == "https://github.com/raulfrk/claude-project-manager.git"

    def test_git_timeout_is_positive(self):
        from installer.local_marketplace import _GIT_TIMEOUT

        assert _GIT_TIMEOUT > 0


class TestRunGit:
    @patch("installer.local_marketplace.subprocess.run")
    def test_success_returns_completed_process(self, mock_run):
        from installer.local_marketplace import _run_git

        mock_run.return_value = MagicMock(returncode=0, stdout="ok\n", stderr="")
        result = _run_git(["status"], cwd=None)
        assert result.returncode == 0
        # stdin=DEVNULL mirrors plugin_cli._run to avoid TTY leakage
        assert mock_run.call_args.kwargs["stdin"] == subprocess.DEVNULL

    @patch("installer.local_marketplace.subprocess.run")
    def test_nonzero_exit_raises_installer_error(self, mock_run):
        from installer.local_marketplace import _run_git

        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="fatal: bad ref\n"
        )
        with pytest.raises(InstallerError) as exc_info:
            _run_git(["checkout", "nope"], cwd=None)
        assert "fatal: bad ref" in str(exc_info.value)

    @patch("installer.local_marketplace.subprocess.run")
    def test_timeout_raises_installer_error(self, mock_run):
        from installer.local_marketplace import _run_git

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="git", timeout=120)
        with pytest.raises(InstallerError) as exc_info:
            _run_git(["clone", "foo"], cwd=None)
        assert "timed out" in str(exc_info.value).lower()

    @patch("installer.local_marketplace.subprocess.run")
    def test_cwd_is_passed_through(self, mock_run):
        from installer.local_marketplace import _run_git

        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        _run_git(["status"], cwd=Path("/tmp/x"))
        assert mock_run.call_args.kwargs["cwd"] == Path("/tmp/x")
