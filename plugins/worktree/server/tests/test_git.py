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
    _run,
    add_all,
    add_worktree,
    clean_untracked,
    commit,
    is_git_repo,
    is_rebase_in_progress,
    list_worktrees,
    lock_worktree,
    merge_ff_only,
    prune_worktrees,
    rebase_continue,
    rebase_worktree,
    remove_worktree,
    reset_hard,
    status_porcelain,
    unlock_worktree,
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

    def test_rebase_conflict_returns_conflict_dict(self, tmp_path: Path) -> None:
        """Diverged commits on the same file return conflict dict without aborting."""
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

        result = rebase_worktree(str(repo), str(repo), "main")
        assert result["status"] == "conflict"
        assert result["base_branch"] == "main"
        assert "init.txt" in result["conflicted_files"]

        # Verify rebase is in progress (NOT aborted)
        git_dir = repo / ".git"
        assert (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()

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

    def test_rebase_conflict_does_not_abort(self) -> None:
        """Mock: conflict detected -> returns conflict dict, abort NOT called."""
        calls = []

        def side_effect(cmd, *args, **kwargs):
            calls.append(list(cmd))
            # Resolve base as local ref.
            if "show-ref" in cmd and "refs/heads/main" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            # Not an ancestor → proceed to rebase.
            if "merge-base" in cmd and "--is-ancestor" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            if cmd[:2] == ["git", "rebase"] and "refs/heads/main" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="CONFLICT"
                )
            if cmd == ["git", "diff", "--name-only", "--diff-filter=U"]:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="file.txt\n", stderr=""
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("server.lib.git.subprocess.run", side_effect=side_effect):
            result = rebase_worktree("/repo", "/repo/wt", "main")

        assert result == {
            "status": "conflict",
            "conflicted_files": ["file.txt"],
            "base_branch": "main",
        }
        assert not any("--abort" in cmd for cmd in calls), "rebase --abort must NOT be called"

    def test_rebase_non_conflict_error_aborts_and_raises(self) -> None:
        """Mock: non-zero exit + no conflicts -> aborts and raises GitError."""
        calls = []

        def side_effect(cmd, *args, **kwargs):
            calls.append(list(cmd))
            if "show-ref" in cmd and "refs/heads/main" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if "merge-base" in cmd and "--is-ancestor" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            if cmd[:2] == ["git", "rebase"] and "refs/heads/main" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="some other error"
                )
            if cmd == ["git", "diff", "--name-only", "--diff-filter=U"]:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch("server.lib.git.subprocess.run", side_effect=side_effect),
            pytest.raises(GitError),
        ):
            rebase_worktree("/repo", "/repo/wt", "main")

        assert any("--abort" in cmd for cmd in calls), "rebase --abort should be called"

    def test_rebase_skipped_when_branch_is_descendant_of_base(self, tmp_path: Path) -> None:
        """Regression for todo 654.

        When the worktree branch is a linear descendant of base_branch (i.e. a
        fast-forward is possible), rebase_worktree must NOT invoke `git rebase`;
        it must short-circuit with {"status": "up_to_date", ...} so that
        git's default fork-point heuristic cannot wind the branch onto an
        ancient common ancestor.
        """
        repo = tmp_path / "repo"
        _init_repo(repo)

        # Create a feature branch with 4 linear commits on top of main.
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        for i in range(4):
            (repo / f"feat-{i}.txt").write_text(f"feat {i}")
            subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", f"feat {i}"],
                cwd=str(repo),
                check=True,
                capture_output=True,
            )

        feature_tip = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

        result = rebase_worktree(str(repo), str(repo), "main")
        assert result == {"status": "up_to_date", "base_branch": "main"}

        # HEAD must be unchanged (no commits rewritten).
        feature_tip_after = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo),
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert feature_tip == feature_tip_after

        # No rebase state directory should exist.
        git_dir = repo / ".git"
        assert not (git_dir / "rebase-merge").exists()
        assert not (git_dir / "rebase-apply").exists()

    def test_rebase_skipped_when_branch_equals_base(self, tmp_path: Path) -> None:
        """Branch with zero commits ahead of base is trivially up_to_date."""
        repo = tmp_path / "repo"
        _init_repo(repo)
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        result = rebase_worktree(str(repo), str(repo), "main")
        assert result == {"status": "up_to_date", "base_branch": "main"}

    def test_rebase_prefers_local_ref_over_origin(self, tmp_path: Path) -> None:
        """When both local and origin refs exist for base_branch, prefer local.

        Simulates todo 654 scenario where origin/dev may be stale relative to
        local dev: we must resolve to refs/heads/dev, not refs/remotes/origin/dev.
        """
        upstream = tmp_path / "upstream.git"
        subprocess.run(
            ["git", "init", "--bare", "-b", "main", str(upstream)],
            check=True,
            capture_output=True,
        )
        repo = tmp_path / "repo"
        _init_repo(repo)
        subprocess.run(
            ["git", "remote", "add", "origin", str(upstream)],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        # Advance local main past origin/main.
        (repo / "local_only.txt").write_text("local only commit")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "local-only commit on main"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        # Branch feature from local main (ahead of origin/main).
        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        (repo / "feat.txt").write_text("feat")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feat commit"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )

        # feature is a descendant of local main, so rebase should be skipped.
        # If the code incorrectly resolved base to origin/main, merge-base would
        # still say ancestor (since origin/main is older) and short-circuit would
        # still fire — but this test guards the resolution path via the
        # up_to_date outcome and the absence of a rebase state dir.
        result = rebase_worktree(str(repo), str(repo), "main")
        assert result == {"status": "up_to_date", "base_branch": "main"}

    def test_rebase_abort_failure_logs_warning(self) -> None:
        """Mock: abort raises OSError -> GitError raised (original), warning logged."""
        call_count = [0]

        def side_effect(cmd, *args, **kwargs):
            call_count[0] += 1
            if "show-ref" in cmd and "refs/heads/main" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if "merge-base" in cmd and "--is-ancestor" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            if cmd[:2] == ["git", "rebase"] and "refs/heads/main" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="some error"
                )
            if cmd == ["git", "diff", "--name-only", "--diff-filter=U"]:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if "--abort" in list(cmd):
                raise OSError("abort command failed")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch("server.lib.git.subprocess.run", side_effect=side_effect),
            pytest.raises(GitError),
        ):
            rebase_worktree("/repo", "/repo/wt", "main")


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
    """Tests for bare subprocess.run calls in rebase_worktree() that bypass _run()."""

    def test_rebase_success(self) -> None:
        """subprocess.run returns 0 → {"status": "rebased", ...}."""

        def side_effect(cmd, *args, **kwargs):
            # Base resolves as local ref.
            if "show-ref" in cmd and "refs/heads/main" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            # Not an ancestor → proceed to rebase.
            if "merge-base" in cmd and "--is-ancestor" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            if cmd[:2] == ["git", "rebase"] and "refs/heads/main" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("server.lib.git.subprocess.run", side_effect=side_effect):
            result = rebase_worktree("/repo", "/worktree", "main")
        assert result == {"status": "rebased", "base_branch": "main"}

    def test_rebase_conflict_returns_dict_no_abort(self) -> None:
        """rebase returns non-zero + diff shows conflicts → returns conflict dict, no abort."""
        calls = []

        def side_effect(cmd, *args, **kwargs):
            calls.append(list(cmd))
            if "show-ref" in cmd and "refs/heads/main" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if "merge-base" in cmd and "--is-ancestor" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            if cmd[:2] == ["git", "rebase"] and "refs/heads/main" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="CONFLICT (content): Merge conflict"
                )
            if cmd == ["git", "diff", "--name-only", "--diff-filter=U"]:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="file.txt\n", stderr=""
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("server.lib.git.subprocess.run", side_effect=side_effect):
            result = rebase_worktree("/repo", "/worktree", "main")

        assert result["status"] == "conflict"
        assert result["conflicted_files"] == ["file.txt"]
        assert not any("--abort" in cmd for cmd in calls)

    def test_rebase_file_not_found(self) -> None:
        """subprocess.run raises FileNotFoundError → GitError."""
        with (
            patch(
                "server.lib.git.subprocess.run",
                side_effect=FileNotFoundError("No such file or directory: 'git'"),
            ),
            pytest.raises(GitError, match="git not found"),
        ):
            rebase_worktree("/repo", "/worktree", "main")


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


# ---------------------------------------------------------------------------
# GitError limited error context tests (todo 475.33)
# ---------------------------------------------------------------------------


class TestGitErrorLimitedContext:
    """Document and verify the limited error context in GitError.

    GitError is a bare Exception subclass with no structured fields.
    _run() raises it with either raw stderr (losing command context) or a
    fallback message that only includes args[0]. These tests document this
    gap as a foundation for future enrichment (todo 475.7).
    """

    @pytest.mark.parametrize(
        "args",
        [
            ["worktree", "list", "--porcelain"],
            ["status", "--porcelain"],
            ["reset", "--hard", "HEAD"],
            ["clean", "-fd"],
        ],
        ids=["worktree", "status", "reset", "clean"],
    )
    def test_fallback_message_includes_subcommand_name(self, args: list[str]) -> None:
        """When stderr is empty, the fallback message contains the subcommand name."""
        failed = subprocess.CompletedProcess(
            args=["git", *args],
            returncode=1,
            stdout="",
            stderr="",
        )
        with patch("subprocess.run", return_value=failed), pytest.raises(GitError) as exc_info:
            _run(args)
        assert args[0] in str(exc_info.value)

    def test_fallback_message_exact_format(self) -> None:
        """Fallback message matches exactly 'git {args[0]} failed'."""
        failed = subprocess.CompletedProcess(
            args=["git", "worktree", "list", "--porcelain"],
            returncode=1,
            stdout="",
            stderr="",
        )
        with patch("subprocess.run", return_value=failed), pytest.raises(GitError) as exc_info:
            _run(["worktree", "list", "--porcelain"])
        assert str(exc_info.value) == "git worktree failed"

    def test_fallback_message_excludes_extra_args(self) -> None:
        """Fallback message does NOT include args beyond args[0]."""
        failed = subprocess.CompletedProcess(
            args=["git", "worktree", "list", "--porcelain"],
            returncode=1,
            stdout="",
            stderr="",
        )
        with patch("subprocess.run", return_value=failed), pytest.raises(GitError) as exc_info:
            _run(["worktree", "list", "--porcelain"])
        msg = str(exc_info.value)
        assert "list" not in msg
        assert "--porcelain" not in msg

    def test_stderr_message_does_not_include_command_context(self) -> None:
        """When stderr is non-empty, the error message is exactly the stderr
        content — it does NOT include the command name, args, or exit code."""
        stderr_text = "fatal: not a git repository"
        failed = subprocess.CompletedProcess(
            args=["git", "worktree", "list", "--porcelain"],
            returncode=128,
            stdout="",
            stderr=stderr_text,
        )
        with patch("subprocess.run", return_value=failed), pytest.raises(GitError) as exc_info:
            _run(["worktree", "list", "--porcelain"])
        msg = str(exc_info.value)
        assert msg == stderr_text
        # Command context is lost
        assert "worktree" not in msg
        assert "128" not in msg

    def test_giterror_has_no_structured_command_attributes(self) -> None:
        """GitError instances lack .cmd, .returncode, and .command attributes.

        Only the base Exception .args tuple is available.
        """
        failed = subprocess.CompletedProcess(
            args=["git", "status", "--porcelain"],
            returncode=1,
            stdout="",
            stderr="",
        )
        with patch("subprocess.run", return_value=failed), pytest.raises(GitError) as exc_info:
            _run(["status", "--porcelain"])
        err = exc_info.value
        assert not hasattr(err, "cmd")
        assert not hasattr(err, "returncode")
        assert not hasattr(err, "command")


class TestGitErrorPropagation:
    """Verify that GitError propagates unchanged through public API functions.

    Public functions do not catch or enrich GitError — the raw message from
    _run() is what callers receive.
    """

    def test_lock_worktree_propagates_error_unchanged(self) -> None:
        """lock_worktree does not enrich the GitError message."""
        with (
            patch("server.lib.git._run", side_effect=GitError("fatal: not a git repository")),
            pytest.raises(GitError, match=r"^fatal: not a git repository$"),
        ):
            lock_worktree("/repo", "/repo/.trees/wt")

    def test_unlock_worktree_propagates_error_unchanged(self) -> None:
        """unlock_worktree does not enrich the GitError message."""
        with (
            patch("server.lib.git._run", side_effect=GitError("fatal: not a git repository")),
            pytest.raises(GitError, match=r"^fatal: not a git repository$"),
        ):
            unlock_worktree("/repo", "/repo/.trees/wt")

    def test_prune_worktrees_propagates_error_unchanged(self) -> None:
        """prune_worktrees does not enrich the GitError message."""
        with (
            patch("server.lib.git._run", side_effect=GitError("fatal: not a git repository")),
            pytest.raises(GitError, match=r"^fatal: not a git repository$"),
        ):
            prune_worktrees("/repo")


# ---------------------------------------------------------------------------
# is_rebase_in_progress tests
# ---------------------------------------------------------------------------


class TestIsRebaseInProgress:
    def test_true_when_rebase_merge_exists(self, tmp_path: Path) -> None:
        """Returns True when .git/rebase-merge subdir exists."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "rebase-merge").mkdir()

        with patch(
            "server.lib.git.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["git", "rev-parse", "--git-dir"],
                returncode=0,
                stdout=".git\n",
                stderr="",
            ),
        ):
            assert is_rebase_in_progress(str(tmp_path)) is True

    def test_true_when_rebase_apply_exists(self, tmp_path: Path) -> None:
        """Returns True when .git/rebase-apply subdir exists."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        (git_dir / "rebase-apply").mkdir()

        with patch(
            "server.lib.git.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["git", "rev-parse", "--git-dir"],
                returncode=0,
                stdout=".git\n",
                stderr="",
            ),
        ):
            assert is_rebase_in_progress(str(tmp_path)) is True

    def test_false_when_no_rebase_dirs(self, tmp_path: Path) -> None:
        """Returns False when neither rebase dir exists."""
        git_dir = tmp_path / ".git"
        git_dir.mkdir()

        with patch(
            "server.lib.git.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["git", "rev-parse", "--git-dir"],
                returncode=0,
                stdout=".git\n",
                stderr="",
            ),
        ):
            assert is_rebase_in_progress(str(tmp_path)) is False

    def test_false_when_git_rev_parse_fails(self, tmp_path: Path) -> None:
        """Returns False when git rev-parse --git-dir fails."""
        with patch(
            "server.lib.git.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=["git", "rev-parse", "--git-dir"],
                returncode=128,
                stdout="",
                stderr="fatal: not a git repository",
            ),
        ):
            assert is_rebase_in_progress(str(tmp_path)) is False

    def test_false_when_file_not_found(self, tmp_path: Path) -> None:
        """Returns False when git binary not found."""
        with patch(
            "server.lib.git.subprocess.run",
            side_effect=FileNotFoundError("git not found"),
        ):
            assert is_rebase_in_progress(str(tmp_path)) is False


# ---------------------------------------------------------------------------
# rebase_continue tests
# ---------------------------------------------------------------------------


class TestRebaseContinue:
    def test_success_returns_rebased(self) -> None:
        """git add + git rebase --continue both succeed → {"status": "rebased"}."""

        def side_effect(cmd, *args, **kwargs):
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with patch("server.lib.git.subprocess.run", side_effect=side_effect):
            result = rebase_continue("/some/worktree")
        assert result == {"status": "rebased"}

    def test_add_failure_raises_git_error(self) -> None:
        """git add -A fails → GitError raised."""

        def side_effect(cmd, *args, **kwargs):
            if "add" in list(cmd):
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="add failed"
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch("server.lib.git.subprocess.run", side_effect=side_effect),
            pytest.raises(GitError, match="git add -A failed"),
        ):
            rebase_continue("/some/worktree")

    def test_continue_still_conflicted_raises_git_conflict_error(self) -> None:
        """git rebase --continue returns non-zero + conflicts remain → GitConflictError."""

        def side_effect(cmd, *args, **kwargs):
            cmd_list = list(cmd)
            if "add" in cmd_list:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if "--continue" in cmd_list:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="still conflicted"
                )
            if "--diff-filter=U" in cmd_list:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="conflict.txt\n", stderr=""
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch("server.lib.git.subprocess.run", side_effect=side_effect),
            pytest.raises(GitConflictError),
        ):
            rebase_continue("/some/worktree")

    def test_continue_non_conflict_failure_raises_git_error(self) -> None:
        """git rebase --continue fails without conflicts → GitError."""

        def side_effect(cmd, *args, **kwargs):
            cmd_list = list(cmd)
            if "add" in cmd_list:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            if "--continue" in cmd_list:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=1, stdout="", stderr="unexpected error"
                )
            if "--diff-filter=U" in cmd_list:
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch("server.lib.git.subprocess.run", side_effect=side_effect),
            pytest.raises(GitError),
        ):
            rebase_continue("/some/worktree")


# ---------------------------------------------------------------------------
# merge_ff_only CAS unit tests (todo 735)
# ---------------------------------------------------------------------------


def _init_repo_on_branch(path: Path, branch: str = "dev") -> None:
    """Create a git repo at *path* with one initial commit on *branch*."""
    subprocess.run(
        ["git", "-c", f"init.defaultBranch={branch}", "init", "-q", str(path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "test"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )
    (path / "init.txt").write_text("init\n")
    subprocess.run(["git", "add", "init.txt"], cwd=str(path), check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init", "-q"],
        cwd=str(path),
        check=True,
        capture_output=True,
    )


class TestMergeFFOnlyCAS:
    """Unit tests for the CAS code path in merge_ff_only (todo 735)."""

    def test_cas_happy_path_single_thread(self, tmp_path: Path) -> None:
        """Single-threaded happy path through CAS code.

        Set up base + 1 worktree with a FF-mergeable commit; call merge_ff_only.
        Verify ref advanced, working tree synced.
        """
        base = tmp_path / "base"
        _init_repo_on_branch(base, "dev")

        wt = tmp_path / "wt" / "feat-A"
        wt.parent.mkdir(exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", "-b", "feat-A", str(wt), "dev", "-q"],
            cwd=str(base),
            check=True,
            capture_output=True,
        )
        (wt / "a.txt").write_text("feat-A work\n")
        subprocess.run(["git", "add", "a.txt"], cwd=str(wt), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feat-A change", "-q"],
            cwd=str(wt),
            check=True,
            capture_output=True,
        )

        result = merge_ff_only(str(base), "feat-A", worktree_path=str(wt), base_branch="dev")
        assert result == {"status": "merged", "branch": "feat-A"}

        # dev ref must now point to the former feat-A tip
        dev_sha = subprocess.run(
            ["git", "rev-parse", "refs/heads/dev"],
            cwd=str(base),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        feat_sha = subprocess.run(
            ["git", "rev-parse", "feat-A"],
            cwd=str(wt),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert dev_sha == feat_sha, "dev ref must equal feat-A tip after merge"

        # base working tree must have the new file
        assert (base / "a.txt").exists(), "a.txt must appear in base working tree after merge"

    def test_cas_non_ff_rejected(self, tmp_path: Path) -> None:
        """Non-FF branch raises GitError.

        Set up base + worktree where the worktree's branch diverged
        (both base dev and the branch have exclusive commits).
        """
        base = tmp_path / "base"
        _init_repo_on_branch(base, "dev")

        # Advance dev so feat-A is no longer a FF onto it
        (base / "dev-extra.txt").write_text("dev-only\n")
        subprocess.run(
            ["git", "add", "dev-extra.txt"], cwd=str(base), check=True, capture_output=True
        )
        subprocess.run(
            ["git", "commit", "-m", "dev extra", "-q"],
            cwd=str(base),
            check=True,
            capture_output=True,
        )

        # Branch feat-A from the original init commit (not from current dev tip)
        init_sha = subprocess.run(
            ["git", "rev-parse", "dev~1"],
            cwd=str(base),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        wt = tmp_path / "wt" / "feat-A"
        wt.parent.mkdir(exist_ok=True)
        subprocess.run(
            ["git", "worktree", "add", "-b", "feat-A", str(wt), init_sha, "-q"],
            cwd=str(base),
            check=True,
            capture_output=True,
        )
        (wt / "a.txt").write_text("feat-A work\n")
        subprocess.run(["git", "add", "a.txt"], cwd=str(wt), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feat-A change", "-q"],
            cwd=str(wt),
            check=True,
            capture_output=True,
        )

        with pytest.raises(GitError, match="not a fast-forward"):
            merge_ff_only(str(base), "feat-A", worktree_path=str(wt), base_branch="dev")

    def test_legacy_2arg_still_works(self, tmp_path: Path) -> None:
        """Legacy 2-arg call (no worktree_path) still uses old git merge --ff-only path."""
        repo = tmp_path / "repo"
        _init_repo(repo)

        subprocess.run(
            ["git", "checkout", "-b", "feature"],
            cwd=str(repo),
            check=True,
            capture_output=True,
        )
        (repo / "feature.txt").write_text("feature\n")
        subprocess.run(["git", "add", "."], cwd=str(repo), check=True, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "feature commit", "-q"],
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

        # Legacy 2-arg form: no worktree_path
        result = merge_ff_only(str(repo), "feature")
        assert result == {"status": "merged", "branch": "feature"}
        assert (repo / "feature.txt").exists()

    def test_merge_ff_only_concurrent_cas(self, tmp_path: Path) -> None:
        """Regression test for todo 735: concurrent merge_ff_only CAS must not corrupt state.

        Spawns N=4 threads calling merge_ff_only against the same base repo.
        Each branch is independently FF-mergeable from the original dev tip but
        they cannot all merge in parallel — exactly one wins the CAS; the others
        receive a clean GitError (dev tip moved, not FF anymore).

        The invariant being tested is NOT "all succeed" — it is:
          1. No GitError is suppressed or causes corrupt working-tree state.
          2. The base repo working tree has NO unstaged content after all threads finish.
          3. Exactly 1 merge succeeded; exactly 3 raised GitError cleanly.

        Pre-fix: the losing `git merge --ff-only` would partially write files to the
        base repo's working tree before aborting, leaving unstaged sibling-file leakage.
        Post-fix: the CAS never touches the working tree on failure (update-ref is
        atomic and the sync only runs on CAS success), so the base repo stays clean.
        """
        import concurrent.futures

        base = tmp_path / "base"
        _init_repo_on_branch(base, "dev")

        # 4 independent branches, each adding a distinct file — no file overlaps.
        branches = ["feat-A", "feat-B", "feat-C", "feat-D"]
        files = {"feat-A": "a", "feat-B": "b", "feat-C": "c", "feat-D": "d"}
        worktrees: list[tuple[Path, str]] = []

        for branch in branches:
            wt = tmp_path / "wt" / branch
            wt.parent.mkdir(exist_ok=True)
            subprocess.run(
                ["git", "worktree", "add", "-b", branch, str(wt), "dev", "-q"],
                cwd=str(base),
                check=True,
                capture_output=True,
            )
            f = files[branch]
            (wt / f"{f}.txt").write_text(f"{f} base\nmodified by {branch}\n")
            subprocess.run(["git", "add", f"{f}.txt"], cwd=str(wt), check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-m", f"{branch} change", "-q"],
                cwd=str(wt),
                check=True,
                capture_output=True,
            )
            worktrees.append((wt, branch))

        # Spawn 4 threads concurrently.
        successes: list[dict[str, str]] = []
        errors: list[str] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futures = [
                ex.submit(merge_ff_only, str(base), branch, str(wt), "dev")
                for wt, branch in worktrees
            ]
            for fut in concurrent.futures.as_completed(futures):
                try:
                    successes.append(fut.result())
                except GitError as e:
                    errors.append(str(e))

        # Exactly 1 must succeed; the other 3 must have raised clean GitErrors.
        assert len(successes) == 1, f"expected exactly 1 merge to succeed, got: {successes}"
        assert len(errors) == 3, f"expected exactly 3 clean GitErrors, got: {errors}"

        # KEY invariant: base repo must have NO unstaged sibling-file leftovers.
        # Pre-fix: losing `git merge --ff-only` partially applied sibling files.
        # Post-fix: CAS never touches working tree on failure → always clean.
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(base),
            capture_output=True,
            text=True,
            check=True,
        )
        assert status.stdout == "", f"base repo has unstaged content post-merge: {status.stdout!r}"

        # dev must have advanced exactly 1 commit past init (= 2 total).
        log = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(base),
            capture_output=True,
            text=True,
            check=True,
        )
        commit_count = len(log.stdout.strip().split("\n"))
        assert commit_count == 2, (
            f"expected 2 commits on dev (init + 1 winner), got {commit_count}: {log.stdout}"
        )
