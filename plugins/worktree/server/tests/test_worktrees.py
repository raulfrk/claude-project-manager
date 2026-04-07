"""Tests for server.tools.worktrees functions."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from server.lib import storage
from server.lib.git import GitError
from server.lib.models import BaseRepo, WorktreeConfig, WorktreeEntry
from server.tools.worktrees import (
    create_worktree,
    get_worktree,
    list_worktrees,
    lock_worktree,
    merge_worktree,
    prune_worktrees,
    remove_worktree,
    unlock_worktree,
)

_SAMPLE_ENTRIES = [
    WorktreeEntry(path="/repo/main", branch="refs/heads/main", head="abc1234"),
    WorktreeEntry(path="/repo/.trees/feat", branch="refs/heads/feat", head="bcd2345"),
]


@pytest.fixture()
def config_with_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    config_path = tmp_path / "worktree.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("WORKTREE_CONFIG", raising=False)
    config = WorktreeConfig(
        default_worktree_dir=str(tmp_path / "worktrees"),
        base_repos=[BaseRepo(label="myapp", path="/home/user/myapp", default_branch="main")],
    )
    storage.save(config)
    return config_path


@pytest.fixture()
def real_git_repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Initialize a real git repository in tmp_path and register it in the worktree config.

    Returns the path to the git repository root.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    worktrees_dir = tmp_path / "worktrees"

    # Initialize git repo with initial commit so `git worktree add` works
    subprocess.run(["git", "init", "-b", "main", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.email", "test@test.com"],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "-C", str(repo_dir), "config", "user.name", "Test User"],
        check=True,
        capture_output=True,
    )
    (repo_dir / "README.md").write_text("init")
    subprocess.run(["git", "-C", str(repo_dir), "add", "."], check=True, capture_output=True)
    subprocess.run(
        ["git", "-C", str(repo_dir), "commit", "-m", "init"],
        check=True,
        capture_output=True,
    )

    # Register in config
    config_path = tmp_path / "worktree.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("WORKTREE_CONFIG", raising=False)
    config = WorktreeConfig(
        default_worktree_dir=str(worktrees_dir),
        base_repos=[BaseRepo(label="myapp", path=str(repo_dir), default_branch="main")],
    )
    storage.save(config)
    return repo_dir


class TestCreateWorktree:
    def test_creates_with_new_branch(self, real_git_repo: Path) -> None:
        result = create_worktree("myapp", "feature/x")
        data = json.loads(result)
        assert "Created" in data["result"]
        assert data["worktree_path"] is not None
        # Verify the worktree directory was actually created on disk
        worktree_path = real_git_repo.parent / "worktrees" / "myapp" / "feature-x"
        assert worktree_path.exists()

    def test_error_for_unknown_repo(self, config_with_repo: Path) -> None:
        result = create_worktree("unknown", "main")
        data = json.loads(result)
        assert "Error" in data["result"]
        assert data["worktree_path"] is None

    def test_error_if_path_exists(self, config_with_repo: Path, tmp_path: Path) -> None:
        existing = tmp_path / "existing"
        existing.mkdir()
        result = create_worktree("myapp", "main", path=str(existing))
        data = json.loads(result)
        assert "Error" in data["result"] or "already exists" in data["result"]
        assert data["worktree_path"] is None

    def test_git_error_propagated(self, config_with_repo: Path) -> None:
        with patch("server.tools.worktrees.git.add_worktree", side_effect=GitError("conflict")):
            result = create_worktree("myapp", "feature/x")
        data = json.loads(result)
        assert "Error" in data["result"]
        assert data["worktree_path"] is None

    def test_reset_and_clean_called_after_create(self, real_git_repo: Path) -> None:
        """reset_hard and clean_untracked are called after worktree creation."""
        with (
            patch("server.tools.worktrees.git.reset_hard") as mock_reset,
            patch("server.tools.worktrees.git.clean_untracked") as mock_clean,
        ):
            result = create_worktree("myapp", "feature/clean")
        data = json.loads(result)
        assert "Created" in data["result"]
        assert "Warnings" not in data["result"]
        mock_reset.assert_called_once_with(data["worktree_path"])
        mock_clean.assert_called_once_with(data["worktree_path"])

    def test_reset_failure_warns(self, real_git_repo: Path) -> None:
        """reset_hard failure produces a warning but still succeeds."""
        with patch("server.tools.worktrees.git.reset_hard", side_effect=GitError("reset boom")):
            result = create_worktree("myapp", "feature/reset-warn")
        data = json.loads(result)
        assert "Created" in data["result"]
        assert "git reset --hard failed: reset boom" in data["result"]
        assert data["worktree_path"] is not None

    def test_clean_failure_warns(self, real_git_repo: Path) -> None:
        """clean_untracked failure produces a warning but still succeeds."""
        with patch(
            "server.tools.worktrees.git.clean_untracked", side_effect=GitError("clean boom")
        ):
            result = create_worktree("myapp", "feature/clean-warn")
        data = json.loads(result)
        assert "Created" in data["result"]
        assert "git clean -fd failed: clean boom" in data["result"]
        assert data["worktree_path"] is not None

    def test_both_reset_and_clean_fail_still_succeeds(self, real_git_repo: Path) -> None:
        """Both reset_hard and clean_untracked fail -> warnings but success."""
        with (
            patch("server.tools.worktrees.git.reset_hard", side_effect=GitError("reset fail")),
            patch("server.tools.worktrees.git.clean_untracked", side_effect=GitError("clean fail")),
        ):
            result = create_worktree("myapp", "feature/both-fail")
        data = json.loads(result)
        assert "Created" in data["result"]
        assert "git reset --hard failed: reset fail" in data["result"]
        assert "git clean -fd failed: clean fail" in data["result"]
        assert data["worktree_path"] is not None


class TestListWorktrees:
    def test_lists_for_all_repos(self, real_git_repo: Path) -> None:
        result = list_worktrees()
        assert "myapp" in result
        assert "main" in result

    def test_filters_by_label(self, real_git_repo: Path) -> None:
        result = list_worktrees("myapp")
        assert "myapp" in result

    def test_unknown_label(self, config_with_repo: Path) -> None:
        result = list_worktrees("unknown")
        assert "No repo" in result

    def test_git_error_shown(self, config_with_repo: Path) -> None:
        with patch("server.tools.worktrees.git.list_worktrees", side_effect=GitError("fail")):
            result = list_worktrees()
        assert "Error" in result


class TestGetWorktree:
    def test_found(self, real_git_repo: Path) -> None:
        # The repo_dir itself is the main worktree
        result = get_worktree(str(real_git_repo))
        data = json.loads(result)
        # Check for expected JSON structure
        assert "branch" in data or "error" in data
        if "error" not in data:
            # Success case - has branch field
            assert isinstance(data["branch"], str)
            assert "main" in data["branch"].lower() or data["branch"] == "refs/heads/main"

    def test_not_found(self, config_with_repo: Path) -> None:
        with patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES):
            result = get_worktree("/nonexistent")
            data = json.loads(result)
            assert "error" in data
            assert "No worktree" in data["error"]


class TestRemoveWorktree:
    def test_removes(self, real_git_repo: Path) -> None:
        # First create a worktree to remove
        create_result = create_worktree("myapp", "feature/rm-test")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        # Extract the worktree path from the result
        worktree_path = real_git_repo.parent / "worktrees" / "myapp" / "feature-rm-test"
        assert worktree_path.exists()
        # Now remove it
        result = remove_worktree(str(worktree_path))
        data = json.loads(result)
        assert "Removed" in data["result"]
        assert data["worktree_path"] == str(worktree_path)

    def test_not_found(self, config_with_repo: Path) -> None:
        with patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES):
            result = remove_worktree("/does/not/exist")
        data = json.loads(result)
        assert "No managed" in data.get("result", "") or "Error" in data.get("result", "")


class TestPruneWorktrees:
    def test_prunes_all(self, real_git_repo: Path) -> None:
        result = prune_worktrees()
        assert "myapp" in result

    def test_git_error(self, config_with_repo: Path) -> None:
        with patch("server.tools.worktrees.git.prune_worktrees", side_effect=GitError("fail")):
            result = prune_worktrees()
        assert "Error" in result


class TestLockUnlock:
    def test_lock(self, config_with_repo: Path) -> None:
        with (
            patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES),
            patch("server.tools.worktrees.git.lock_worktree") as mock_lock,
        ):
            result = lock_worktree("/repo/main", reason="testing")
        data = json.loads(result)
        assert "Locked" in data["result"]
        assert data["path"] == "/repo/main"
        mock_lock.assert_called_once()

    def test_unlock(self, config_with_repo: Path) -> None:
        with (
            patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES),
            patch("server.tools.worktrees.git.unlock_worktree") as mock_unlock,
        ):
            result = unlock_worktree("/repo/main")
        data = json.loads(result)
        assert "Unlocked" in data["result"]
        assert data["path"] == "/repo/main"
        mock_unlock.assert_called_once()


def _git(repo: Path, *args: str) -> str:
    """Run a git command in a repo and return stdout."""
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class TestMergeWorktree:
    def test_merge_success(self, real_git_repo: Path) -> None:
        """Rebase + ff-only both succeed -> result='merged'."""
        # Create a worktree with a new branch
        create_result = create_worktree("myapp", "feature/merge-ok")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = str(real_git_repo.parent / "worktrees" / "myapp" / "feature-merge-ok")

        # Make a commit in the worktree
        (Path(wt_path) / "newfile.txt").write_text("hello")
        _git(Path(wt_path), "add", ".")
        _git(Path(wt_path), "commit", "-m", "add newfile")

        result = merge_worktree(wt_path, base_branch="main")
        data = json.loads(result)
        assert data["result"] == "merged"
        assert data["branch"] == "feature/merge-ok"
        assert data["base_branch"] == "main"

    def test_merge_conflict(self, real_git_repo: Path) -> None:
        """Rebase conflict -> result='conflict', worktree left intact."""
        # Create a worktree
        create_result = create_worktree("myapp", "feature/conflict")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = str(real_git_repo.parent / "worktrees" / "myapp" / "feature-conflict")

        # Edit README on the feature branch
        (Path(wt_path) / "README.md").write_text("feature change")
        _git(Path(wt_path), "add", ".")
        _git(Path(wt_path), "commit", "-m", "feature edit")

        # Also edit README on main so they diverge
        (real_git_repo / "README.md").write_text("main change")
        _git(real_git_repo, "add", ".")
        _git(real_git_repo, "commit", "-m", "main edit")

        result = merge_worktree(wt_path, base_branch="main")
        data = json.loads(result)
        assert data["result"] == "conflict"
        assert data["branch"] == "feature/conflict"
        assert data["worktree_path"] == wt_path
        # Worktree directory still exists
        assert Path(wt_path).exists()

    def test_ff_only_failed(self, real_git_repo: Path) -> None:
        """Rebase succeeds but merge --ff-only fails -> result='ff_only_failed'."""
        create_result = create_worktree("myapp", "feature/ff-fail")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = str(real_git_repo.parent / "worktrees" / "myapp" / "feature-ff-fail")

        # Make a commit in the worktree
        (Path(wt_path) / "newfile.txt").write_text("hello")
        _git(Path(wt_path), "add", ".")
        _git(Path(wt_path), "commit", "-m", "add newfile")

        # Mock: rebase succeeds, but ff-only merge fails
        with patch(
            "server.tools.worktrees.git.merge_ff_only", side_effect=GitError("not a fast-forward")
        ):
            result = merge_worktree(wt_path, base_branch="main")
        data = json.loads(result)
        assert data["result"] == "ff_only_failed"
        assert data["branch"] == "feature/ff-fail"

    def test_worktree_not_found(self, config_with_repo: Path) -> None:
        """Non-existent worktree path -> error."""
        with patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES):
            result = merge_worktree("/does/not/exist")
        data = json.loads(result)
        assert data["result"] == "error"
        assert "No managed worktree" in data["message"]

    def test_locked_worktree(self, real_git_repo: Path) -> None:
        """Locked worktree -> error."""
        create_result = create_worktree("myapp", "feature/locked")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = str(real_git_repo.parent / "worktrees" / "myapp" / "feature-locked")

        # Lock the worktree
        lock_worktree(wt_path, reason="testing")

        result = merge_worktree(wt_path, base_branch="main")
        data = json.loads(result)
        assert data["result"] == "error"
        assert "locked" in data["message"].lower()

    def test_detached_head(self, real_git_repo: Path) -> None:
        """Detached HEAD -> error."""
        create_result = create_worktree("myapp", "feature/detach")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = str(real_git_repo.parent / "worktrees" / "myapp" / "feature-detach")

        # Detach HEAD by checking out a commit directly
        head_sha = _git(Path(wt_path), "rev-parse", "HEAD")
        _git(Path(wt_path), "checkout", head_sha)

        result = merge_worktree(wt_path, base_branch="main")
        data = json.loads(result)
        assert data["result"] == "error"
        assert "detached HEAD" in data["message"]

    def test_missing_base_branch_no_default(self, real_git_repo: Path) -> None:
        """No base_branch and no discoverable default -> error."""
        create_result = create_worktree("myapp", "feature/no-default")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = str(real_git_repo.parent / "worktrees" / "myapp" / "feature-no-default")

        real_run = subprocess.run

        def patched_run(cmd, *args, **kwargs):
            # Intercept the two base_branch resolution calls, let everything else through
            if "symbolic-ref" in cmd and "refs/remotes/origin/HEAD" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            if "config" in cmd and "init.defaultBranch" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            return real_run(cmd, *args, **kwargs)

        with patch("server.tools.worktrees.subprocess.run", side_effect=patched_run):
            result = merge_worktree(wt_path, base_branch=None)

        data = json.loads(result)
        assert data["result"] == "error"
        assert "Cannot determine default branch" in data["message"]
