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


class TestIsValidClone:
    def test_false_when_dir_missing(self, tmp_path):
        from installer.local_marketplace import _is_valid_clone

        assert _is_valid_clone(tmp_path / "missing") is False

    def test_false_when_not_a_git_repo(self, tmp_path):
        from installer.local_marketplace import _is_valid_clone

        # A dir with contents but no .git
        (tmp_path / "file.txt").write_text("hi")
        assert _is_valid_clone(tmp_path) is False

    @patch("installer.local_marketplace._run_git")
    def test_false_when_origin_url_mismatches(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _is_valid_clone

        (tmp_path / ".git").mkdir()
        mock_run_git.return_value = MagicMock(stdout="git@github.com:other/repo.git\n")
        assert _is_valid_clone(tmp_path) is False

    @patch("installer.local_marketplace._run_git")
    def test_true_when_origin_url_matches(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _HTTPS_SOURCE, _is_valid_clone

        (tmp_path / ".git").mkdir()
        mock_run_git.return_value = MagicMock(stdout=f"{_HTTPS_SOURCE}\n")
        assert _is_valid_clone(tmp_path) is True

    @patch("installer.local_marketplace._run_git")
    def test_false_when_git_command_fails(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _is_valid_clone

        (tmp_path / ".git").mkdir()
        mock_run_git.side_effect = InstallerError("no origin")
        assert _is_valid_clone(tmp_path) is False


class TestDefaultBranch:
    @patch("installer.local_marketplace._run_git")
    def test_returns_branch_name_from_symref(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _default_branch

        mock_run_git.return_value = MagicMock(stdout="refs/remotes/origin/dev\n")
        assert _default_branch(tmp_path) == "dev"

    @patch("installer.local_marketplace._run_git")
    def test_strips_refs_remotes_origin_prefix(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _default_branch

        mock_run_git.return_value = MagicMock(stdout="refs/remotes/origin/main\n")
        assert _default_branch(tmp_path) == "main"

    @patch("installer.local_marketplace._run_git")
    def test_falls_back_to_main_when_symref_not_set(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _default_branch

        # origin/HEAD is not always set in a fresh clone without --origin-head
        mock_run_git.side_effect = InstallerError(
            "ref refs/remotes/origin/HEAD is not a symbolic ref"
        )
        assert _default_branch(tmp_path) == "main"

    @patch("installer.local_marketplace._run_git")
    def test_handles_branch_with_slash(self, mock_run_git, tmp_path):
        from installer.local_marketplace import _default_branch

        mock_run_git.return_value = MagicMock(
            stdout="refs/remotes/origin/feature/auth\n"
        )
        assert _default_branch(tmp_path) == "feature/auth"


class TestEnsureLocalClone:
    @patch("installer.local_marketplace.shutil.which", return_value="/usr/bin/git")
    @patch("installer.local_marketplace._is_valid_clone", return_value=False)
    @patch("installer.local_marketplace._run_git")
    def test_clones_when_dir_missing(
        self, mock_run_git, _is_valid, _which, tmp_path, monkeypatch
    ):
        from installer.local_marketplace import _HTTPS_SOURCE, ensure_local_clone

        clone_dir = tmp_path / "mk"
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", clone_dir)
        mock_run_git.return_value = MagicMock(stdout="", stderr="")
        returned = ensure_local_clone(branch="dev")
        # First call must be the clone
        first_call_args = mock_run_git.call_args_list[0].args[0]
        assert first_call_args[0] == "clone"
        assert _HTTPS_SOURCE in first_call_args
        assert str(clone_dir) in first_call_args
        assert returned == clone_dir

    @patch("installer.local_marketplace.shutil.which", return_value="/usr/bin/git")
    @patch("installer.local_marketplace._is_valid_clone", return_value=True)
    @patch("installer.local_marketplace._run_git")
    def test_fetches_and_resets_when_clone_exists(
        self, mock_run_git, _is_valid, _which, tmp_path, monkeypatch
    ):
        from installer.local_marketplace import ensure_local_clone

        clone_dir = tmp_path / "mk"
        clone_dir.mkdir()
        (clone_dir / ".git").mkdir()
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", clone_dir)
        mock_run_git.return_value = MagicMock(stdout="", stderr="")
        ensure_local_clone(branch="dev")
        # Verify fetch, checkout, reset were called in order
        calls = [c.args[0] for c in mock_run_git.call_args_list]
        assert ["fetch", "origin"] in calls
        assert ["checkout", "dev"] in calls
        assert ["reset", "--hard", "origin/dev"] in calls

    @patch("installer.local_marketplace.shutil.which", return_value="/usr/bin/git")
    @patch("installer.local_marketplace._is_valid_clone", return_value=True)
    @patch("installer.local_marketplace._default_branch", return_value="main")
    @patch("installer.local_marketplace._run_git")
    def test_uses_default_branch_when_branch_none(
        self, mock_run_git, _default, _is_valid, _which, tmp_path, monkeypatch
    ):
        from installer.local_marketplace import ensure_local_clone

        clone_dir = tmp_path / "mk"
        clone_dir.mkdir()
        (clone_dir / ".git").mkdir()
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", clone_dir)
        mock_run_git.return_value = MagicMock(stdout="", stderr="")
        ensure_local_clone(branch=None)
        calls = [c.args[0] for c in mock_run_git.call_args_list]
        assert ["checkout", "main"] in calls
        assert ["reset", "--hard", "origin/main"] in calls

    @patch("installer.local_marketplace.shutil.which", return_value=None)
    def test_raises_when_git_not_on_path(self, _which, monkeypatch, tmp_path):
        from installer.local_marketplace import ensure_local_clone

        monkeypatch.setattr(
            "installer.local_marketplace.LOCAL_CLONE_DIR", tmp_path / "mk"
        )
        with pytest.raises(InstallerError) as exc_info:
            ensure_local_clone(branch=None)
        assert "git" in str(exc_info.value).lower()

    @patch("installer.local_marketplace.shutil.which", return_value="/usr/bin/git")
    def test_raises_when_existing_dir_is_not_valid_clone(
        self, _which, tmp_path, monkeypatch
    ):
        from installer.local_marketplace import ensure_local_clone

        clone_dir = tmp_path / "mk"
        clone_dir.mkdir()
        (clone_dir / "stray-file.txt").write_text("not a clone")
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", clone_dir)
        with pytest.raises(InstallerError) as exc_info:
            ensure_local_clone(branch=None)
        assert "not a valid clone" in str(exc_info.value).lower()

    @patch("installer.local_marketplace.shutil.which", return_value="/usr/bin/git")
    @patch("installer.local_marketplace._run_git")
    def test_creates_parent_dir_before_clone(
        self, mock_run_git, _which, tmp_path, monkeypatch
    ):
        from installer.local_marketplace import ensure_local_clone

        clone_dir = tmp_path / "deeply" / "nested" / "mk"
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", clone_dir)
        mock_run_git.return_value = MagicMock(stdout="", stderr="")
        ensure_local_clone(branch=None)
        assert clone_dir.parent.exists()
