"""Tests for server.lib.git (subprocess git wrapper)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from server.lib.git import (
    GitError,
    _parse_porcelain,
    add_worktree,
    is_git_repo,
    list_worktrees,
    remove_worktree,
)

PORCELAIN_SAMPLE = """\
worktree /home/user/myapp
HEAD abc1234def5678901234567890123456789abcde
branch refs/heads/main

worktree /home/user/myapp/.trees/feature-auth
HEAD bbb2345def5678901234567890123456789abcde
branch refs/heads/feature/auth

worktree /home/user/myapp/.trees/hotfix
HEAD ccc3456def5678901234567890123456789abcde
detached
locked
prunable gitdir file points to non-existent location

"""


def test_parse_porcelain_main_worktree() -> None:
    entries = _parse_porcelain(PORCELAIN_SAMPLE)
    assert len(entries) == 3
    main = entries[0]
    assert main.path == "/home/user/myapp"
    assert main.branch == "refs/heads/main"
    assert not main.detached
    assert not main.locked


def test_parse_porcelain_detached_locked_prunable() -> None:
    entries = _parse_porcelain(PORCELAIN_SAMPLE)
    hotfix = entries[2]
    assert hotfix.detached
    assert hotfix.locked
    assert hotfix.prunable


def test_parse_porcelain_feature_branch() -> None:
    entries = _parse_porcelain(PORCELAIN_SAMPLE)
    feat = entries[1]
    assert feat.branch == "refs/heads/feature/auth"
    assert not feat.locked


class TestIsGitRepo:
    def test_valid_repo(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
        assert is_git_repo(str(tmp_path))

    def test_non_repo(self, tmp_path: Path) -> None:
        assert not is_git_repo(str(tmp_path))


class TestListWorktrees:
    def test_calls_git_with_porcelain(self) -> None:
        with patch("server.lib.git._run") as mock_run:
            mock_run.return_value = PORCELAIN_SAMPLE
            entries = list_worktrees("/some/repo")
        mock_run.assert_called_once_with(["worktree", "list", "--porcelain"], cwd="/some/repo")
        assert len(entries) == 3

    def test_raises_git_error_on_failure(self) -> None:
        with (
            patch("server.lib.git._run", side_effect=GitError("not a git repo")),
            pytest.raises(GitError),
        ):
            list_worktrees("/not/a/repo")


class TestAddWorktree:
    def test_calls_git_with_new_branch(self, tmp_path: Path) -> None:
        with patch("server.lib.git._run") as mock_run:
            mock_run.return_value = ""
            result = add_worktree("/repo", str(tmp_path / "wt"), "feature/x", new_branch=True)
        args = mock_run.call_args[0][0]
        assert "-b" in args
        assert str(tmp_path / "wt") in args
        assert result == str(tmp_path / "wt")

    def test_new_branch_flag_precedes_branch_name_not_path(self, tmp_path: Path) -> None:
        """Verify -b is followed by branch name, not the worktree path."""
        with patch("server.lib.git._run") as mock_run:
            mock_run.return_value = ""
            add_worktree("/repo", str(tmp_path / "wt"), "feature/x", new_branch=True)
        args = mock_run.call_args[0][0]
        b_index = args.index("-b")
        assert args[b_index + 1] == "feature/x", "branch name must follow -b"
        assert args[b_index + 2] == str(tmp_path / "wt"), "worktree path must come after branch name"

    def test_calls_git_without_new_branch(self, tmp_path: Path) -> None:
        with patch("server.lib.git._run") as mock_run:
            mock_run.return_value = ""
            add_worktree("/repo", str(tmp_path / "wt"), "main", new_branch=False)
        args = mock_run.call_args[0][0]
        assert "-b" not in args


class TestRemoveWorktree:
    def test_calls_git_remove(self) -> None:
        with patch("server.lib.git._run") as mock_run:
            mock_run.return_value = ""
            remove_worktree("/repo", "/repo/.trees/wt")
        args = mock_run.call_args[0][0]
        assert "remove" in args
        assert "--force" not in args

    def test_calls_git_remove_force(self) -> None:
        with patch("server.lib.git._run") as mock_run:
            mock_run.return_value = ""
            remove_worktree("/repo", "/repo/.trees/wt", force=True)
        args = mock_run.call_args[0][0]
        assert "--force" in args


# ---------------------------------------------------------------------------
# Subprocess error scenario tests
# ---------------------------------------------------------------------------

class TestRunSubprocessErrors:
    """Tests that _run (and callers) propagate subprocess-level failures correctly."""

    def test_file_not_found_raises_file_not_found_error(self) -> None:
        """If git binary is missing, subprocess.run raises FileNotFoundError."""
        with (
            patch("subprocess.run", side_effect=FileNotFoundError("git not found")),
            pytest.raises(FileNotFoundError),
        ):
            list_worktrees("/some/repo")

    def test_subprocess_error_propagates_from_list_worktrees(self) -> None:
        """Generic SubprocessError (e.g. broken pipe) propagates uncaught from list_worktrees."""
        with (
            patch("subprocess.run", side_effect=subprocess.SubprocessError("broken pipe")),
            pytest.raises(subprocess.SubprocessError),
        ):
            list_worktrees("/some/repo")

    def test_subprocess_error_propagates_from_add_worktree(self, tmp_path: Path) -> None:
        """Generic SubprocessError propagates uncaught from add_worktree."""
        with (
            patch("subprocess.run", side_effect=subprocess.SubprocessError("pipe closed")),
            pytest.raises(subprocess.SubprocessError),
        ):
            add_worktree("/repo", str(tmp_path / "wt"), "feature/x", new_branch=True)

    def test_called_process_error_on_nonzero_returncode(self) -> None:
        """CalledProcessError raised by subprocess is NOT caught; it propagates."""
        err = subprocess.CalledProcessError(128, ["git", "worktree", "list"])
        with (
            patch("subprocess.run", side_effect=err),
            pytest.raises(subprocess.CalledProcessError),
        ):
            list_worktrees("/some/repo")

    def test_nonzero_returncode_raises_git_error(self) -> None:
        """When subprocess.run returns a non-zero exit code, _run raises GitError."""
        failed = subprocess.CompletedProcess(
            args=["git", "worktree", "list", "--porcelain"],
            returncode=128,
            stdout="",
            stderr="fatal: not a git repository",
        )
        with (
            patch("subprocess.run", return_value=failed),
            pytest.raises(GitError, match="not a git repository"),
        ):
            list_worktrees("/not/a/repo")

    def test_nonzero_returncode_no_stderr_uses_fallback_message(self) -> None:
        """GitError fallback message is used when stderr is empty."""
        failed = subprocess.CompletedProcess(
            args=["git", "worktree", "list", "--porcelain"],
            returncode=1,
            stdout="",
            stderr="",
        )
        with (
            patch("subprocess.run", return_value=failed),
            pytest.raises(GitError, match="worktree failed"),
        ):
            list_worktrees("/some/repo")

    def test_timeout_expired_propagates_from_list_worktrees(self) -> None:
        """TimeoutExpired is a SubprocessError subclass and propagates uncaught."""
        timeout_err = subprocess.TimeoutExpired(cmd=["git", "worktree", "list"], timeout=5)
        with (
            patch("subprocess.run", side_effect=timeout_err),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            list_worktrees("/some/repo")

    def test_timeout_expired_propagates_from_add_worktree(self, tmp_path: Path) -> None:
        """TimeoutExpired propagates uncaught from add_worktree."""
        timeout_err = subprocess.TimeoutExpired(cmd=["git", "worktree", "add"], timeout=5)
        with (
            patch("subprocess.run", side_effect=timeout_err),
            pytest.raises(subprocess.TimeoutExpired),
        ):
            add_worktree("/repo", str(tmp_path / "wt"), "feature/x", new_branch=True)


# ---------------------------------------------------------------------------
# Corrupted / unexpected git output tests
# ---------------------------------------------------------------------------

class TestParsePorcelainCorruptedOutput:
    """Tests for _parse_porcelain with edge-case and malformed input."""

    def test_empty_output_returns_empty_list(self) -> None:
        """Empty string yields an empty list (no worktrees)."""
        assert _parse_porcelain("") == []

    def test_whitespace_only_output_returns_empty_list(self) -> None:
        """Output that is only blank lines yields an empty list."""
        assert _parse_porcelain("\n\n\n") == []

    def test_missing_head_line_uses_empty_string(self) -> None:
        """A worktree block without a HEAD line still parses; head defaults to ''."""
        output = "worktree /some/path\nbranch refs/heads/main\n\n"
        entries = _parse_porcelain(output)
        assert len(entries) == 1
        assert entries[0].head == ""

    def test_missing_branch_line_uses_detached_default(self) -> None:
        """A worktree block without a branch line defaults branch to 'detached'."""
        output = "worktree /some/path\nHEAD abc1234\n\n"
        entries = _parse_porcelain(output)
        assert len(entries) == 1
        assert entries[0].branch == "detached"

    def test_missing_worktree_path_uses_empty_string(self) -> None:
        """A block without a 'worktree' line produces path='' (degenerate but safe)."""
        output = "HEAD abc1234\nbranch refs/heads/main\n\n"
        entries = _parse_porcelain(output)
        assert len(entries) == 1
        assert entries[0].path == ""

    def test_unknown_lines_are_ignored(self) -> None:
        """Unrecognised lines in a block are silently skipped."""
        output = (
            "worktree /some/path\n"
            "HEAD abc1234\n"
            "branch refs/heads/main\n"
            "unknown-key some-value\n"
            "\n"
        )
        entries = _parse_porcelain(output)
        assert len(entries) == 1
        assert entries[0].path == "/some/path"

    def test_no_trailing_newline_still_parsed(self) -> None:
        """A valid block without a trailing blank line is still captured via the end-of-loop flush."""
        output = "worktree /some/path\nHEAD abc1234\nbranch refs/heads/main"
        entries = _parse_porcelain(output)
        assert len(entries) == 1
        assert entries[0].branch == "refs/heads/main"

    def test_bare_worktree_parsed_correctly(self) -> None:
        """A bare worktree block sets bare=True."""
        output = "worktree /some/bare.git\nHEAD abc1234\nbare\n\n"
        entries = _parse_porcelain(output)
        assert len(entries) == 1
        assert entries[0].bare is True

    def test_list_worktrees_empty_output_returns_empty_list(self) -> None:
        """list_worktrees with empty git output returns []."""
        with patch("server.lib.git._run", return_value=""):
            result = list_worktrees("/some/repo")
        assert result == []

    def test_list_worktrees_single_block_no_trailing_newline(self) -> None:
        """list_worktrees handles output with no trailing blank line."""
        output = "worktree /main\nHEAD abc\nbranch refs/heads/main"
        with patch("server.lib.git._run", return_value=output):
            result = list_worktrees("/some/repo")
        assert len(result) == 1
        assert result[0].path == "/main"
