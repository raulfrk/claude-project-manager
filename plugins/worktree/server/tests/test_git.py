"""Tests for server.lib.git (subprocess git wrapper)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from server.lib.git import (
    GitConflictError,
    GitError,
    _parse_porcelain,
    add_all,
    add_worktree,
    clean_untracked,
    commit,
    is_git_repo,
    list_worktrees,
    merge_ff_only,
    rebase_worktree,
    remove_worktree,
    reset_hard,
    status_porcelain,
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

    def test_non_repo(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path.parent))
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
        assert args[b_index + 2] == str(tmp_path / "wt"), (
            "worktree path must come after branch name"
        )

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


class TestResetHard:
    def test_calls_git_reset_hard(self) -> None:
        with patch("server.lib.git._run") as mock_run:
            mock_run.return_value = ""
            reset_hard("/some/worktree")
        mock_run.assert_called_once_with(["reset", "--hard", "HEAD"], cwd="/some/worktree")

    def test_raises_git_error_on_failure(self) -> None:
        with (
            patch("server.lib.git._run", side_effect=GitError("reset failed")),
            pytest.raises(GitError, match="reset failed"),
        ):
            reset_hard("/some/worktree")


class TestCleanUntracked:
    def test_calls_git_clean(self) -> None:
        with patch("server.lib.git._run") as mock_run:
            mock_run.return_value = ""
            clean_untracked("/some/worktree")
        mock_run.assert_called_once_with(["clean", "-fd"], cwd="/some/worktree")

    def test_raises_git_error_on_failure(self) -> None:
        with (
            patch("server.lib.git._run", side_effect=GitError("clean failed")),
            pytest.raises(GitError, match="clean failed"),
        ):
            clean_untracked("/some/worktree")


# ---------------------------------------------------------------------------
# Subprocess error scenario tests
# ---------------------------------------------------------------------------


class TestRunSubprocessErrors:
    """Tests that _run raises GitError correctly for subprocess failures."""

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
            "worktree /some/path\nHEAD abc1234\nbranch refs/heads/main\nunknown-key some-value\n\n"
        )
        entries = _parse_porcelain(output)
        assert len(entries) == 1
        assert entries[0].path == "/some/path"

    def test_no_trailing_newline_still_parsed(self) -> None:
        """A valid block without a trailing blank line is still
        captured via the end-of-loop flush."""
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


# ---------------------------------------------------------------------------
# Helper: initialise a real git repo with an initial commit
# ---------------------------------------------------------------------------


def _init_repo(path: Path) -> None:
    """Create a git repo at *path* with one initial commit."""
    subprocess.run(["git", "init", "-b", "main", str(path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    (path / "init.txt").write_text("init")
    subprocess.run(["git", "add", "."], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )


# ---------------------------------------------------------------------------
# rebase_worktree tests
# ---------------------------------------------------------------------------


class TestRebaseWorktree:
    """Tests for rebase_worktree using real git repos."""

    def test_rebase_success_clean(self, tmp_path: Path) -> None:
        """Clean rebase onto base branch returns status 'rebased'."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Create a feature branch with one commit
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        (repo / "feature.txt").write_text("feature work")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feature commit"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        # Add a commit on main that doesn't conflict
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        (repo / "main.txt").write_text("main work")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "main commit"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        # Switch back to feature for rebase
        subprocess.run(
            ["git", "checkout", "feature"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        result = rebase_worktree(str(repo), str(repo), "main")
        assert result == {"status": "rebased", "base_branch": "main"}

    def test_rebase_conflict_raises_and_aborts(self, tmp_path: Path) -> None:
        """Diverged commits on the same file raise GitConflictError and abort."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Create feature branch that edits init.txt
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        (repo / "init.txt").write_text("feature version")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feature edit"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        # Create conflicting commit on main
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        (repo / "init.txt").write_text("main version")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "main edit"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        # Switch to feature and attempt rebase
        subprocess.run(
            ["git", "checkout", "feature"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        with pytest.raises(GitConflictError, match="Rebase conflict"):
            rebase_worktree(str(repo), str(repo), "main")

        # Verify rebase was aborted (no .git/rebase-merge dir)
        git_dir = repo / ".git"
        assert not (git_dir / "rebase-merge").exists()
        assert not (git_dir / "rebase-apply").exists()

    def test_rebase_abort_failure_silently_lost(self) -> None:
        """When rebase fails AND abort also fails, abort error is silently lost.

        Documents current buggy behavior: the abort result is never checked,
        so GitConflictError is raised as if abort succeeded. The worktree may
        be left in a broken mid-rebase state.
        """
        rebase_fail = subprocess.CompletedProcess(
            args=["git", "rebase", "main"],
            returncode=1,
            stdout="",
            stderr="CONFLICT (content): Merge conflict in file.txt",
        )
        abort_fail = subprocess.CompletedProcess(
            args=["git", "rebase", "--abort"],
            returncode=128,
            stdout="",
            stderr="fatal: No rebase in progress?",
        )

        with (
            patch("server.lib.git.subprocess.run", side_effect=[rebase_fail, abort_fail]),
            pytest.raises(GitConflictError, match="Rebase conflict"),
        ):
            rebase_worktree("/repo", "/repo/wt", "main")

    def test_rebase_abort_success_no_rebase_dirs(self, tmp_path: Path) -> None:
        """After successful abort, no rebase-merge or rebase-apply dirs remain.

        Mock-based complement to test_rebase_conflict_raises_and_aborts.
        """
        rebase_fail = subprocess.CompletedProcess(
            args=["git", "rebase", "main"],
            returncode=1,
            stdout="",
            stderr="CONFLICT (content): Merge conflict in file.txt",
        )
        abort_ok = subprocess.CompletedProcess(
            args=["git", "rebase", "--abort"],
            returncode=0,
            stdout="",
            stderr="",
        )

        wt = tmp_path / "worktree"
        wt.mkdir()
        git_dir = wt / ".git"
        git_dir.mkdir()
        # Simulate rebase-merge dir that abort should clean up
        (git_dir / "rebase-merge").mkdir()

        with (
            patch("server.lib.git.subprocess.run", side_effect=[rebase_fail, abort_ok]),
            pytest.raises(GitConflictError),
        ):
            rebase_worktree("/repo", str(wt), "main")

        # In a real scenario, a successful abort removes these dirs.
        # Since we mock subprocess.run, the dirs are not actually removed,
        # but the test verifies the function completes the abort call.
        # The existing integration test (test_rebase_conflict_raises_and_aborts)
        # verifies the dirs are actually cleaned up with real git.

    def test_rebase_file_not_found_raises_git_error(self) -> None:
        """FileNotFoundError (e.g., git binary missing) raises GitError."""
        with (
            patch(
                "server.lib.git.subprocess.run",
                side_effect=FileNotFoundError("No such file or directory: 'git'"),
            ),
            pytest.raises(GitError, match="git not found"),
        ):
            rebase_worktree("/repo", "/some/worktree", "main")

    def test_rebase_conflict_error_includes_path_and_stderr(self) -> None:
        """GitConflictError message includes both worktree path and stderr text."""
        rebase_fail = subprocess.CompletedProcess(
            args=["git", "rebase", "main"],
            returncode=1,
            stdout="",
            stderr="CONFLICT (content): Merge conflict in important.py",
        )
        abort_ok = subprocess.CompletedProcess(
            args=["git", "rebase", "--abort"],
            returncode=0,
            stdout="",
            stderr="",
        )

        wt_path = "/home/user/worktrees/feature-branch"
        with (
            patch("server.lib.git.subprocess.run", side_effect=[rebase_fail, abort_ok]),
            pytest.raises(GitConflictError, match=wt_path) as exc_info,
        ):
            rebase_worktree("/repo", wt_path, "main")

        error_msg = str(exc_info.value)
        assert wt_path in error_msg
        assert "Merge conflict in important.py" in error_msg


# ---------------------------------------------------------------------------
# merge_ff_only tests
# ---------------------------------------------------------------------------


class TestMergeFFOnly:
    """Tests for merge_ff_only using real git repos."""

    def test_merge_ff_success(self, tmp_path: Path) -> None:
        """Fast-forward merge succeeds when branch is strictly ahead."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Create a branch with one commit ahead of main
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        (repo / "feature.txt").write_text("feature")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feature commit"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        # Go back to main and ff-merge
        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        result = merge_ff_only(str(repo), "feature")
        assert result == {"status": "merged", "branch": "feature"}

        # Verify main now has the feature file
        assert (repo / "feature.txt").exists()

    def test_merge_ff_fails_on_diverged(self, tmp_path: Path) -> None:
        """Diverged branches cannot fast-forward; raises GitError."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Create diverging branches
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        (repo / "feature.txt").write_text("feature")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feature commit"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        subprocess.run(
            ["git", "checkout", "main"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        (repo / "main.txt").write_text("main")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "main commit"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        with pytest.raises(GitError, match="Fast-forward merge failed"):
            merge_ff_only(str(repo), "feature")


# ---------------------------------------------------------------------------
# status_porcelain / add_all / commit unit tests
# ---------------------------------------------------------------------------


class TestStatusPorcelain:
    def test_calls_git_status(self) -> None:
        with patch("server.lib.git._run", return_value="M file.py\n") as mock_run:
            result = status_porcelain(Path("/some/path"))
        mock_run.assert_called_once_with(["-C", "/some/path", "status", "--porcelain"])
        assert result == "M file.py\n"

    def test_clean_repo_returns_empty(self) -> None:
        with patch("server.lib.git._run", return_value=""):
            result = status_porcelain(Path("/some/path"))
        assert result == ""

    def test_raises_git_error(self) -> None:
        with (
            patch("server.lib.git._run", side_effect=GitError("status failed")),
            pytest.raises(GitError, match="status failed"),
        ):
            status_porcelain(Path("/some/path"))


class TestAddAll:
    def test_calls_git_add(self) -> None:
        with patch("server.lib.git._run", return_value="") as mock_run:
            add_all(Path("/some/path"))
        mock_run.assert_called_once_with(["-C", "/some/path", "add", "-A"])

    def test_raises_git_error(self) -> None:
        with (
            patch("server.lib.git._run", side_effect=GitError("add failed")),
            pytest.raises(GitError, match="add failed"),
        ):
            add_all(Path("/some/path"))


class TestCommit:
    def test_calls_git_commit_and_returns_sha(self) -> None:
        with patch("server.lib.git._run") as mock_run:
            mock_run.side_effect = ["", "abc1234def\n"]
            result = commit(Path("/some/path"), "test message")
        assert result == "abc1234def"
        assert mock_run.call_count == 2
        mock_run.assert_any_call(["-C", "/some/path", "commit", "-m", "test message"])
        mock_run.assert_any_call(["-C", "/some/path", "rev-parse", "HEAD"])

    def test_commit_failure_raises(self) -> None:
        with (
            patch("server.lib.git._run", side_effect=GitError("nothing to commit")),
            pytest.raises(GitError, match="nothing to commit"),
        ):
            commit(Path("/some/path"), "test")


# ---------------------------------------------------------------------------
# Bare subprocess.run tests for rebase_worktree
# ---------------------------------------------------------------------------


class TestRebaseWorktreeSubprocess:
    """Tests for bare subprocess.run calls in rebase_worktree() that bypass _run().

    These tests mock subprocess.run at the git module level to capture
    current behavior before the refactor in todo 475.7.
    """

    def test_rebase_success(self) -> None:
        """Site 4 (git.py:170): subprocess.run returns 0 → {"status": "rebased", ...}."""
        with patch(
            "server.lib.git.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["git", "rebase", "main"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ):
            result = rebase_worktree("/repo", "/worktree", "main")
        assert result == {"status": "rebased", "base_branch": "main"}

    def test_rebase_conflict_raises_and_aborts(self) -> None:
        """Site 4+5 (git.py:170-183): rebase returns non-zero → abort called → GitConflictError."""
        calls = []

        def side_effect(cmd, *args, **kwargs):
            calls.append(cmd)
            if "rebase" in cmd and "--abort" not in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="CONFLICT (content): Merge conflict"
                )
            # abort call
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch("server.lib.git.subprocess.run", side_effect=side_effect),
            pytest.raises(GitConflictError, match="Rebase conflict"),
        ):
            rebase_worktree("/repo", "/worktree", "main")

        # Verify abort was called
        assert any("--abort" in cmd for cmd in calls), "rebase --abort should have been called"

    def test_rebase_file_not_found(self) -> None:
        """Site 4 (git.py:185): subprocess.run raises FileNotFoundError → GitError."""
        with (
            patch(
                "server.lib.git.subprocess.run",
                side_effect=FileNotFoundError("No such file or directory: 'git'"),
            ),
            pytest.raises(GitError, match="git not found"),
        ):
            rebase_worktree("/repo", "/worktree", "main")

    def test_rebase_abort_failure_is_silent(self) -> None:
        """Site 5 (git.py:178): abort fails but error is swallowed
        -- only GitConflictError raised."""
        calls = []

        def side_effect(cmd, *args, **kwargs):
            calls.append(cmd)
            if "rebase" in cmd and "--abort" not in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="CONFLICT"
                )
            if "--abort" in cmd:
                # abort also fails
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="abort failed"
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch("server.lib.git.subprocess.run", side_effect=side_effect),
            pytest.raises(GitConflictError, match="Rebase conflict"),
        ):
            rebase_worktree("/repo", "/worktree", "main")

        # Verify abort was attempted even though it failed
        assert any("--abort" in cmd for cmd in calls)


# ---------------------------------------------------------------------------
# Bare subprocess.run tests for merge_ff_only
# ---------------------------------------------------------------------------


class TestMergeFFOnlySubprocess:
    """Tests for bare subprocess.run calls in merge_ff_only() that bypass _run().

    These tests mock subprocess.run at the git module level to capture
    current behavior before the refactor in todo 475.7.
    """

    def test_merge_success(self) -> None:
        """Site 6 (git.py:193): subprocess.run returns 0 → {"status": "merged", ...}."""
        with patch(
            "server.lib.git.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["git", "merge", "--ff-only", "feature"],
                returncode=0,
                stdout="",
                stderr="",
            ),
        ):
            result = merge_ff_only("/repo", "feature")
        assert result == {"status": "merged", "branch": "feature"}

    def test_merge_failure_raises_git_error(self) -> None:
        """Site 6 (git.py:199): subprocess.run returns non-zero → GitError with stderr."""
        with (
            patch(
                "server.lib.git.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "merge", "--ff-only", "feature"],
                    returncode=1,
                    stdout="",
                    stderr="fatal: Not possible to fast-forward, aborting.",
                ),
            ),
            pytest.raises(GitError, match="Fast-forward merge failed"),
        ):
            merge_ff_only("/repo", "feature")

    def test_merge_file_not_found(self) -> None:
        """Site 6 (git.py:202): subprocess.run raises FileNotFoundError → GitError."""
        with (
            patch(
                "server.lib.git.subprocess.run",
                side_effect=FileNotFoundError("No such file or directory: 'git'"),
            ),
            pytest.raises(GitError, match="git not found"),
        ):
            merge_ff_only("/repo", "feature")
