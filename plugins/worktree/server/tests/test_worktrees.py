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
    _resolve_worktree_path,
    auto_commit,
    create_worktree,
    get_worktree,
    list_worktrees,
    lock_worktree,
    merge_worktree,
    prune_worktrees,
    rebase_continue_worktree,
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

    def test_git_error_when_path_exists(self, config_with_repo: Path, tmp_path: Path) -> None:
        """Bug #14 fix: no pre-check; git is the authority. If path exists and git fails,
        the GitError is surfaced as an error response."""
        existing = tmp_path / "existing"
        existing.mkdir()
        with patch(
            "server.tools.worktrees.git.add_worktree",
            side_effect=GitError("fatal: destination path already exists"),
        ):
            result = create_worktree("myapp", "main", path=str(existing))
        data = json.loads(result)
        assert "Error" in data["result"]
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

    def test_add_worktree_failure_triggers_cleanup(self, config_with_repo: Path) -> None:
        """add_worktree GitError -> remove_worktree called for cleanup, error JSON returned."""
        with (
            patch(
                "server.tools.worktrees.git.add_worktree",
                side_effect=GitError("branch already exists"),
            ) as mock_add,
            patch("server.tools.worktrees.git.remove_worktree") as mock_remove,
        ):
            result = create_worktree("myapp", "feature/conflict")
        data = json.loads(result)
        assert "Error" in data["result"]
        assert data["worktree_path"] is None
        mock_add.assert_called_once()
        mock_remove.assert_called_once()
        # force=True must be passed for cleanup
        _, kwargs = mock_remove.call_args
        assert kwargs.get("force") is True

    def test_add_worktree_failure_cleanup_error_suppressed(self, config_with_repo: Path) -> None:
        """add_worktree fails AND remove_worktree raises -> secondary error silenced."""
        with (
            patch(
                "server.tools.worktrees.git.add_worktree",
                side_effect=GitError("conflict"),
            ),
            patch(
                "server.tools.worktrees.git.remove_worktree",
                side_effect=GitError("cleanup failed"),
            ),
        ):
            result = create_worktree("myapp", "feature/conflict2")
        data = json.loads(result)
        assert "Error" in data["result"]
        assert data["worktree_path"] is None

    def test_toctou_race_path_created_between_check_and_add(self, real_git_repo: Path) -> None:
        """Bug #14: if another process creates the worktree dir between check and git call,
        git.add_worktree raises GitError which must be propagated as an error (not suppressed)."""
        with patch(
            "server.tools.worktrees.git.add_worktree",
            side_effect=GitError("worktree directory already exists"),
        ):
            result = create_worktree("myapp", "feature/race")
        data = json.loads(result)
        assert "Error" in data["result"]
        assert data["worktree_path"] is None

    def test_no_precheck_path_exists_allows_git_to_decide(
        self, real_git_repo: Path, tmp_path: Path
    ) -> None:
        """Bug #14 fix: create_worktree must NOT reject when path exists on disk but git succeeds.
        (i.e. the exists() pre-check is removed so git is the authority)."""
        # Create the target directory first to simulate a race
        target = real_git_repo.parent / "worktrees" / "myapp" / "feature-precheck"
        target.mkdir(parents=True, exist_ok=True)
        # With the pre-check removed, git decides: if git succeeds, we succeed
        with (
            patch("server.tools.worktrees.git.add_worktree") as mock_add,
            patch("server.tools.worktrees.git.reset_hard"),
            patch("server.tools.worktrees.git.clean_untracked"),
        ):
            mock_add.return_value = None
            result = create_worktree("myapp", "feature/precheck", path=str(target))
        data = json.loads(result)
        assert "Created" in data["result"]
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

    def test_locked_returns_error(self, real_git_repo: Path) -> None:
        """Locked worktree + force=False -> error, no removal."""
        create_result = create_worktree("myapp", "feature/locked-rm")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = str(real_git_repo.parent / "worktrees" / "myapp" / "feature-locked-rm")

        lock_worktree(wt_path, reason="testing lock check")

        result = remove_worktree(wt_path, force=False)
        data = json.loads(result)
        assert data["result"] == "error"
        assert "locked" in data["message"].lower()
        assert "wt_unlock" in data["message"] or "force=true" in data["message"]
        assert Path(wt_path).exists()

    def test_locked_force_bypasses_check(self, real_git_repo: Path) -> None:
        """Locked worktree + force=True -> removed successfully."""
        create_result = create_worktree("myapp", "feature/locked-force")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = str(real_git_repo.parent / "worktrees" / "myapp" / "feature-locked-force")

        lock_worktree(wt_path, reason="testing force bypass")

        result = remove_worktree(wt_path, force=True)
        data = json.loads(result)
        assert "Removed" in data["result"]
        assert data["worktree_path"] == wt_path


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

    def test_merge_success_non_main_base_branch(self, real_git_repo: Path) -> None:
        """Merge with base_branch='develop' (non-main) works correctly."""
        # Create a 'develop' branch in the base repo
        _git(real_git_repo, "branch", "develop")

        # Create a worktree off develop
        create_result = create_worktree("myapp", "feature/dev-merge")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = str(real_git_repo.parent / "worktrees" / "myapp" / "feature-dev-merge")

        # Make a commit in the worktree
        (Path(wt_path) / "devfile.txt").write_text("develop feature")
        _git(Path(wt_path), "add", ".")
        _git(Path(wt_path), "commit", "-m", "add devfile")

        result = merge_worktree(wt_path, base_branch="develop")
        data = json.loads(result)
        assert data["result"] == "merged"
        assert data["branch"] == "feature/dev-merge"
        assert data["base_branch"] == "develop"

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

    def test_merge_conflict_rebase_left_in_progress(self, real_git_repo: Path) -> None:
        """AC1: After conflict, rebase is left in progress for model to resolve."""
        create_result = create_worktree("myapp", "feature/conflict-abort")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = real_git_repo.parent / "worktrees" / "myapp" / "feature-conflict-abort"

        # Edit README on feature branch
        (wt_path / "README.md").write_text("feature side")
        _git(wt_path, "add", ".")
        _git(wt_path, "commit", "-m", "feature edit")

        # Edit README on main to create conflict
        (real_git_repo / "README.md").write_text("main side")
        _git(real_git_repo, "add", ".")
        _git(real_git_repo, "commit", "-m", "main edit")

        result = merge_worktree(str(wt_path), base_branch="main")
        data = json.loads(result)
        assert data["result"] == "conflict"
        assert "conflicted_files" in data
        assert isinstance(data["conflicted_files"], list)

        # Rebase is still in progress (NOT aborted)
        git_dir = _git(wt_path, "rev-parse", "--git-dir")
        git_dir_path = Path(git_dir) if Path(git_dir).is_absolute() else wt_path / git_dir
        rebase_in_progress = (git_dir_path / "rebase-merge").exists() or (
            git_dir_path / "rebase-apply"
        ).exists()
        assert rebase_in_progress, "rebase should be left in progress for model resolution"

    def test_merge_conflict_includes_conflicted_files(self, real_git_repo: Path) -> None:
        """AC2: Conflict response includes conflicted_files list."""
        create_result = create_worktree("myapp", "feature/conflict-msg")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = real_git_repo.parent / "worktrees" / "myapp" / "feature-conflict-msg"

        (wt_path / "README.md").write_text("feature msg")
        _git(wt_path, "add", ".")
        _git(wt_path, "commit", "-m", "feature edit")

        (real_git_repo / "README.md").write_text("main msg")
        _git(real_git_repo, "add", ".")
        _git(real_git_repo, "commit", "-m", "main edit")

        result = merge_worktree(str(wt_path), base_branch="main")
        data = json.loads(result)
        assert data["result"] == "conflict"
        # conflicted_files should list the conflicting file
        assert "conflicted_files" in data
        assert isinstance(data["conflicted_files"], list)
        assert len(data["conflicted_files"]) > 0
        assert any("README.md" in f for f in data["conflicted_files"])

    def test_merge_conflict_worktree_remains_usable_after_abort(self, real_git_repo: Path) -> None:
        """AC3: After conflict + manual abort, worktree is functional."""
        create_result = create_worktree("myapp", "feature/conflict-usable")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = real_git_repo.parent / "worktrees" / "myapp" / "feature-conflict-usable"

        (wt_path / "README.md").write_text("feature usable")
        _git(wt_path, "add", ".")
        _git(wt_path, "commit", "-m", "feature edit")

        (real_git_repo / "README.md").write_text("main usable")
        _git(real_git_repo, "add", ".")
        _git(real_git_repo, "commit", "-m", "main edit")

        result = merge_worktree(str(wt_path), base_branch="main")
        data = json.loads(result)
        assert data["result"] == "conflict"
        assert "conflicted_files" in data

        # Manually abort the rebase so the worktree is clean
        _git(wt_path, "rebase", "--abort")

        # Branch is still checked out (not detached HEAD)
        head_ref = _git(wt_path, "symbolic-ref", "HEAD")
        assert head_ref == "refs/heads/feature/conflict-usable"

        # A subsequent merge can succeed after the conflict source is resolved.
        # Reset the feature branch to main (so they share history), then add
        # a non-conflicting commit.
        _git(wt_path, "reset", "--hard", "main")
        (wt_path / "feature-only.txt").write_text("no conflict")
        _git(wt_path, "add", ".")
        _git(wt_path, "commit", "-m", "non-conflicting change")

        result2 = merge_worktree(str(wt_path), base_branch="main")
        data2 = json.loads(result2)
        assert data2["result"] == "merged"

    def test_merge_conflict_with_diff_detection(self, real_git_repo: Path) -> None:
        """AC4: Rebase fails + diff detects conflicts -> conflict dict returned."""
        create_result = create_worktree("myapp", "feature/abort-fail")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path_p = real_git_repo.parent / "worktrees" / "myapp" / "feature-abort-fail"
        wt_path = str(wt_path_p)

        # Create divergence so the branch is NOT already a descendant of main
        # (otherwise rebase_worktree short-circuits to up_to_date; todo 654).
        (wt_path_p / "feat.txt").write_text("feat work")
        _git(wt_path_p, "add", ".")
        _git(wt_path_p, "commit", "-m", "feat commit")
        (real_git_repo / "main.txt").write_text("main work")
        _git(real_git_repo, "add", ".")
        _git(real_git_repo, "commit", "-m", "main commit")

        real_run = subprocess.run

        call_count = {"rebase": 0}

        def patched_run(cmd, *args, **kwargs):
            cmd_list = list(cmd)
            if "rebase" in cmd_list and "--abort" not in cmd_list and "--continue" not in cmd_list:
                call_count["rebase"] += 1
                # Initial rebase fails (conflict)
                return subprocess.CompletedProcess(
                    args=cmd,
                    returncode=1,
                    stdout="",
                    stderr="CONFLICT (content): Merge conflict in README.md",
                )
            if "--diff-filter=U" in cmd_list:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="README.md\n", stderr=""
                )
            return real_run(cmd, *args, **kwargs)

        with patch("server.lib.git.subprocess.run", side_effect=patched_run):
            result = merge_worktree(wt_path, base_branch="main")

        data = json.loads(result)
        assert data["result"] == "conflict"
        assert "conflicted_files" in data
        assert call_count["rebase"] == 1

    def test_merge_conflict_no_worktree_commits(self, real_git_repo: Path) -> None:
        """AC5: Conflict with no additional commits on worktree branch."""
        create_result = create_worktree("myapp", "feature/no-commits")
        create_data = json.loads(create_result)
        assert "Created" in create_data["result"]
        wt_path = real_git_repo.parent / "worktrees" / "myapp" / "feature-no-commits"

        # Don't make any commits on the feature branch.
        # Instead, make a commit on main that diverges from the branch point.
        # The worktree branch was created from main's HEAD, so it shares
        # the same README.md. We need to make a commit on main that changes
        # README.md, then also commit a change on the worktree branch so
        # there's an actual conflict during rebase.
        (real_git_repo / "README.md").write_text("main diverged")
        _git(real_git_repo, "add", ".")
        _git(real_git_repo, "commit", "-m", "main diverge")

        # Make a single conflicting commit on the worktree branch
        (wt_path / "README.md").write_text("worktree diverged")
        _git(wt_path, "add", ".")
        _git(wt_path, "commit", "-m", "worktree single edit")

        result = merge_worktree(str(wt_path), base_branch="main")
        data = json.loads(result)
        assert data["result"] == "conflict"
        assert data["branch"] == "feature/no-commits"
        assert "conflicted_files" in data
        assert isinstance(data["conflicted_files"], list)


# ---------------------------------------------------------------------------
# _resolve_worktree_path: slash-to-dash substitution tests
# ---------------------------------------------------------------------------


class TestResolveWorktreePath:
    """Unit tests for the `/` → `-` branch name substitution in _resolve_worktree_path."""

    def test_single_slash_replaced(self, config_with_repo: Path, tmp_path: Path) -> None:
        """AC-1.1: branch with single `/` gets slash replaced with dash."""
        result = _resolve_worktree_path("myapp", "feature/foo", None)
        expected = str(tmp_path / "worktrees" / "myapp" / "feature-foo")
        assert result == expected

    def test_multiple_slashes_all_replaced(self, config_with_repo: Path, tmp_path: Path) -> None:
        """AC-1.2: branch with multiple `/` has ALL slashes replaced."""
        result = _resolve_worktree_path("myapp", "user/feature/deep", None)
        expected = str(tmp_path / "worktrees" / "myapp" / "user-feature-deep")
        assert result == expected

    def test_no_slash_unchanged(self, config_with_repo: Path, tmp_path: Path) -> None:
        """AC-1.3: branch with no `/` is returned unchanged in the path."""
        result = _resolve_worktree_path("myapp", "main", None)
        expected = str(tmp_path / "worktrees" / "myapp" / "main")
        assert result == expected

    def test_custom_path_bypasses_substitution(
        self, config_with_repo: Path, tmp_path: Path
    ) -> None:
        """AC-1.4: custom_path is used as-is, no slash substitution applied."""
        custom = str(tmp_path / "my/custom/path")
        result = _resolve_worktree_path("myapp", "feature/x", custom)
        # custom_path is resolved, so compare resolved form
        assert result == str(Path(custom).resolve())
        # The branch slash should NOT appear in the result
        assert "feature-x" not in result


class TestCreateWorktreePathResolution:
    """Integration tests verifying path resolution through create_worktree."""

    def test_multi_segment_branch_path(self, real_git_repo: Path) -> None:
        """AC-2.1: create_worktree with multi-segment branch uses substituted path."""
        result = create_worktree("myapp", "user/feature/deep")
        data = json.loads(result)
        assert "Created" in data["result"]
        assert data["worktree_path"] is not None
        worktree_path = real_git_repo.parent / "worktrees" / "myapp" / "user-feature-deep"
        assert worktree_path.exists()
        assert str(worktree_path) == data["worktree_path"]

    def test_custom_path_ignores_substitution(self, real_git_repo: Path, tmp_path: Path) -> None:
        """AC-2.2: create_worktree with custom_path ignores slash substitution."""
        custom = str(tmp_path / "custom-wt")
        result = create_worktree("myapp", "user/feature/deep", path=custom)
        data = json.loads(result)
        assert "Created" in data["result"]
        assert data["worktree_path"] == custom
        assert Path(custom).exists()


# ---------------------------------------------------------------------------
# Gap tests: untested error/edge paths
# ---------------------------------------------------------------------------


class TestCreateWorktreeEdgeCases:
    def test_empty_branch_name(self, config_with_repo: Path) -> None:
        result = create_worktree("myapp", "")
        data = json.loads(result)
        assert "Error" in data["result"]
        assert "empty" in data["result"].lower()
        assert data["worktree_path"] is None

    def test_whitespace_branch_name(self, config_with_repo: Path) -> None:
        result = create_worktree("myapp", "   ")
        data = json.loads(result)
        assert "Error" in data["result"]
        assert data["worktree_path"] is None


class TestListWorktreesEdgeCases:
    def test_no_repos_configured(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "worktree.yaml"
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
        monkeypatch.delenv("WORKTREE_CONFIG", raising=False)
        storage.save(WorktreeConfig(base_repos=[]))
        result = list_worktrees()
        assert "No base repos" in result


class TestPruneWorktreesEdgeCases:
    def test_unknown_label(self, config_with_repo: Path) -> None:
        result = prune_worktrees("unknown")
        assert "No repo" in result

    def test_no_repos_configured(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        config_path = tmp_path / "worktree.yaml"
        monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
        monkeypatch.delenv("WORKTREE_CONFIG", raising=False)
        storage.save(WorktreeConfig(base_repos=[]))
        result = prune_worktrees()
        assert "No repos configured" in result


class TestLockUnlockEdgeCases:
    def test_lock_not_found(self, config_with_repo: Path) -> None:
        with patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES):
            result = lock_worktree("/nonexistent/path")
        data = json.loads(result)
        assert "error" in data
        assert "No managed" in data["error"]

    def test_unlock_not_found(self, config_with_repo: Path) -> None:
        with patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES):
            result = unlock_worktree("/nonexistent/path")
        data = json.loads(result)
        assert "error" in data
        assert "No managed" in data["error"]

    def test_lock_git_error(self, config_with_repo: Path) -> None:
        with (
            patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES),
            patch(
                "server.tools.worktrees.git.lock_worktree",
                side_effect=GitError("already locked"),
            ),
        ):
            result = lock_worktree("/repo/main", reason="test")
        data = json.loads(result)
        assert "error" in data
        assert "already locked" in data["error"]

    def test_unlock_git_error(self, config_with_repo: Path) -> None:
        with (
            patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES),
            patch(
                "server.tools.worktrees.git.unlock_worktree",
                side_effect=GitError("not locked"),
            ),
        ):
            result = unlock_worktree("/repo/main")
        data = json.loads(result)
        assert "error" in data
        assert "not locked" in data["error"]

    def test_lock_race_condition_not_a_worktree(self, config_with_repo: Path) -> None:
        """lock_worktree: git raises 'not a worktree' -> structured error JSON returned."""
        with (
            patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES),
            patch(
                "server.tools.worktrees.git.lock_worktree",
                side_effect=GitError("fatal: '/repo/main' is not a worktree"),
            ),
        ):
            result = lock_worktree("/repo/main", reason="test")
        data = json.loads(result)
        assert "error" in data
        assert "may have been removed" in data["error"]
        assert "/repo/main" in data["error"]

    def test_lock_race_condition_no_such_file(self, config_with_repo: Path) -> None:
        """lock_worktree: git raises 'no such file' -> structured error JSON returned."""
        with (
            patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES),
            patch(
                "server.tools.worktrees.git.lock_worktree",
                side_effect=GitError("error: no such file or directory"),
            ),
        ):
            result = lock_worktree("/repo/main")
        data = json.loads(result)
        assert "error" in data
        assert "may have been removed" in data["error"]

    def test_unlock_race_condition_not_a_worktree(self, config_with_repo: Path) -> None:
        """unlock_worktree: git raises 'not a working tree' -> structured error JSON returned."""
        with (
            patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES),
            patch(
                "server.tools.worktrees.git.unlock_worktree",
                side_effect=GitError("fatal: '/repo/main' is not a working tree"),
            ),
        ):
            result = unlock_worktree("/repo/main")
        data = json.loads(result)
        assert "error" in data
        assert "may have been removed" in data["error"]
        assert "/repo/main" in data["error"]

    def test_unlock_race_condition_no_such_file(self, config_with_repo: Path) -> None:
        """unlock_worktree: git raises 'no such file' -> structured error JSON returned."""
        with (
            patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES),
            patch(
                "server.tools.worktrees.git.unlock_worktree",
                side_effect=GitError("no such file or directory"),
            ),
        ):
            result = unlock_worktree("/repo/main")
        data = json.loads(result)
        assert "error" in data
        assert "may have been removed" in data["error"]

    def test_lock_non_race_git_error_preserved(self, config_with_repo: Path) -> None:
        """lock_worktree: unrecognised GitError re-raised (not swallowed as race condition)."""
        with (
            patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES),
            patch(
                "server.tools.worktrees.git.lock_worktree",
                side_effect=GitError("permission denied"),
            ),
        ):
            result = lock_worktree("/repo/main")
        data = json.loads(result)
        assert "error" in data
        assert "permission denied" in data["error"]
        assert "may have been removed" not in data["error"]


class TestRemoveWorktreeEdgeCases:
    def test_git_error_includes_tip(self, config_with_repo: Path) -> None:
        with (
            patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES),
            patch(
                "server.tools.worktrees.git.remove_worktree",
                side_effect=GitError("has changes"),
            ),
        ):
            result = remove_worktree("/repo/main")
        data = json.loads(result)
        assert "has changes" in data["result"]
        assert "force=true" in data["result"]


# ---------------------------------------------------------------------------
# auto_commit tests
# ---------------------------------------------------------------------------


class TestAutoCommit:
    def test_dirty_worktree(self, tmp_path: Path) -> None:
        """Dirty worktree is staged, committed, and returns committed=true."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch("server.tools.worktrees.git.status_porcelain", return_value="M file.py\n"),
            patch("server.tools.worktrees.git.add_all") as mock_add,
            patch("server.tools.worktrees.git.commit", return_value="abc1234") as mock_commit,
        ):
            result = auto_commit(str(wt), "test commit")
        data = json.loads(result)
        assert data["committed"] is True
        assert data["files_committed"] == 1
        assert data["commit_sha"] == "abc1234"
        assert data["result"] == "auto-committed"
        mock_add.assert_called_once()
        mock_commit.assert_called_once()

    def test_clean_worktree(self, tmp_path: Path) -> None:
        """Clean worktree returns committed=false."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch("server.tools.worktrees.git.status_porcelain", return_value=""),
        ):
            result = auto_commit(str(wt))
        data = json.loads(result)
        assert data["committed"] is False
        assert data["result"] == "clean"
        assert data["files_committed"] == 0
        assert data["commit_sha"] is None

    def test_untracked_only(self, tmp_path: Path) -> None:
        """Untracked files are committed."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch("server.tools.worktrees.git.status_porcelain", return_value="?? new_file.py\n"),
            patch("server.tools.worktrees.git.add_all"),
            patch("server.tools.worktrees.git.commit", return_value="def5678"),
        ):
            result = auto_commit(str(wt))
        data = json.loads(result)
        assert data["committed"] is True
        assert data["files_committed"] == 1

    def test_deletions_only(self, tmp_path: Path) -> None:
        """Deleted files are committed."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch("server.tools.worktrees.git.status_porcelain", return_value=" D deleted.py\n"),
            patch("server.tools.worktrees.git.add_all"),
            patch("server.tools.worktrees.git.commit", return_value="aaa1111"),
        ):
            result = auto_commit(str(wt))
        data = json.loads(result)
        assert data["committed"] is True
        assert data["files_committed"] == 1

    def test_missing_path(self, tmp_path: Path) -> None:
        """Non-existent path returns error."""
        result = auto_commit(str(tmp_path / "nonexistent"))
        data = json.loads(result)
        assert data["result"] == "error"
        assert "does not exist" in data["error"]

    def test_not_git_repo(self, tmp_path: Path) -> None:
        """Path that is not a git repo returns error."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with patch("server.tools.worktrees.git.is_git_repo", return_value=False):
            result = auto_commit(str(wt))
        data = json.loads(result)
        assert data["result"] == "error"
        assert "Not a git repository" in data["error"]

    def test_git_commit_failure(self, tmp_path: Path) -> None:
        """GitError during commit returns warning, no crash."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch("server.tools.worktrees.git.status_porcelain", return_value="M file.py\n"),
            patch("server.tools.worktrees.git.add_all"),
            patch("server.tools.worktrees.git.commit", side_effect=GitError("commit failed")),
        ):
            result = auto_commit(str(wt))
        data = json.loads(result)
        assert data["result"] == "warning"
        assert "commit failed" in data["error"]

    def test_git_add_failure(self, tmp_path: Path) -> None:
        """GitError during add returns warning, no crash."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch("server.tools.worktrees.git.status_porcelain", return_value="M file.py\n"),
            patch("server.tools.worktrees.git.add_all", side_effect=GitError("add failed")),
        ):
            result = auto_commit(str(wt))
        data = json.loads(result)
        assert data["result"] == "warning"
        assert "add failed" in data["error"]

    def test_multiple_files(self, tmp_path: Path) -> None:
        """Multiple changed files are counted correctly."""
        wt = tmp_path / "wt"
        wt.mkdir()
        status = "M file1.py\nM file2.py\n?? file3.py\n"
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch("server.tools.worktrees.git.status_porcelain", return_value=status),
            patch("server.tools.worktrees.git.add_all"),
            patch("server.tools.worktrees.git.commit", return_value="bbb2222"),
        ):
            result = auto_commit(str(wt))
        data = json.loads(result)
        assert data["committed"] is True
        assert data["files_committed"] == 3

    def test_status_failure(self, tmp_path: Path) -> None:
        """GitError during status_porcelain returns error."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch(
                "server.tools.worktrees.git.status_porcelain",
                side_effect=GitError("status failed"),
            ),
        ):
            result = auto_commit(str(wt))
        data = json.loads(result)
        assert data["result"] == "error"
        assert "status failed" in data["error"]

    def test_skip_hooks_threaded_to_git_commit(self, tmp_path: Path) -> None:
        """skip_hooks=True is forwarded to git.commit (todo 821 last-resort bypass)."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch("server.tools.worktrees.git.status_porcelain", return_value="M file.py\n"),
            patch("server.tools.worktrees.git.add_all"),
            patch("server.tools.worktrees.git.commit", return_value="ddd4444") as mock_commit,
        ):
            result = auto_commit(str(wt), "msg", skip_hooks=True)
        data = json.loads(result)
        assert data["committed"] is True
        # First positional arg is the path; check skip_hooks kwarg routed through.
        _, kwargs = mock_commit.call_args
        assert kwargs.get("skip_hooks") is True

    def test_skip_hooks_default_false(self, tmp_path: Path) -> None:
        """Default skip_hooks=False — hooks run as normal."""
        wt = tmp_path / "wt"
        wt.mkdir()
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch("server.tools.worktrees.git.status_porcelain", return_value="M file.py\n"),
            patch("server.tools.worktrees.git.add_all"),
            patch("server.tools.worktrees.git.commit", return_value="eee5555") as mock_commit,
        ):
            auto_commit(str(wt), "msg")
        _, kwargs = mock_commit.call_args
        assert kwargs.get("skip_hooks") is False


# ---------------------------------------------------------------------------
# Bare subprocess.run call tests for merge_worktree
# ---------------------------------------------------------------------------


class TestMergeWorktreeBareSubprocess:
    """Tests for bare subprocess.run calls in merge_worktree() that bypass git.py.

    These tests mock subprocess.run at the worktrees module level to capture
    current behavior before the refactor in todo 475.7.
    """

    def test_detached_head_detection(self, config_with_repo: Path) -> None:
        """Site 1 (worktrees.py:248): symbolic-ref HEAD non-zero
        -> error JSON with 'detached HEAD'."""
        with (
            patch(
                "server.tools.worktrees._find_worktree",
                return_value=("/worktree/path", "/repo/path"),
            ),
            patch(
                "server.tools.worktrees.git.list_worktrees",
                return_value=[],
            ),
            patch(
                "server.tools.worktrees.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "-C", "/worktree/path", "symbolic-ref", "HEAD"],
                    returncode=1,
                    stdout="",
                    stderr="fatal: ref HEAD is not a symbolic ref",
                ),
            ),
        ):
            result = merge_worktree("/worktree/path", base_branch="main")
        data = json.loads(result)
        assert data["result"] == "error"
        assert "detached HEAD" in data["message"]

    def test_detached_head_file_not_found(self, config_with_repo: Path) -> None:
        """Site 1 (worktrees.py:258): FileNotFoundError
        -> error JSON with 'git not found'."""
        with (
            patch(
                "server.tools.worktrees._find_worktree",
                return_value=("/worktree/path", "/repo/path"),
            ),
            patch(
                "server.tools.worktrees.git.list_worktrees",
                return_value=[],
            ),
            patch(
                "server.tools.worktrees.subprocess.run",
                side_effect=FileNotFoundError("No such file or directory: 'git'"),
            ),
        ):
            result = merge_worktree("/worktree/path", base_branch="main")
        data = json.loads(result)
        assert data["result"] == "error"
        assert "git not found" in data["message"]

    def test_origin_head_resolution_success(self, config_with_repo: Path) -> None:
        """Site 2 (worktrees.py:266): origin/HEAD succeeds
        -> base_branch set from output."""

        def side_effect(cmd, *args, **kwargs):
            if "symbolic-ref" in cmd and "HEAD" in cmd and "origin" not in str(cmd):
                # symbolic-ref HEAD → success (not detached)
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="refs/heads/feature\n", stderr=""
                )
            if "symbolic-ref" in cmd and "refs/remotes/origin/HEAD" in cmd:
                # origin HEAD → success
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="refs/remotes/origin/main\n", stderr=""
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch(
                "server.tools.worktrees._find_worktree",
                return_value=("/worktree/path", "/repo/path"),
            ),
            patch("server.tools.worktrees.git.list_worktrees", return_value=[]),
            patch("server.tools.worktrees.subprocess.run", side_effect=side_effect),
            patch(
                "server.tools.worktrees.git.rebase_worktree",
                return_value={"status": "rebased", "base_branch": "main"},
            ),
            patch(
                "server.tools.worktrees.git.merge_ff_only",
                return_value={"status": "merged", "branch": "feature"},
            ),
            patch("server.tools.worktrees.git.remove_worktree"),
        ):
            result = merge_worktree("/worktree/path")  # no base_branch
        data = json.loads(result)
        # Should succeed — base_branch resolved from origin/HEAD
        assert data["result"] != "error"

    def test_origin_head_fallback_to_init_default_branch(self, config_with_repo: Path) -> None:
        """Site 3 (worktrees.py:274): origin/HEAD fails,
        init.defaultBranch succeeds -> base_branch from config."""

        def side_effect(cmd, *args, **kwargs):
            if "symbolic-ref" in cmd and "refs/remotes/origin/HEAD" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            if "symbolic-ref" in cmd and "HEAD" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="refs/heads/feature\n", stderr=""
                )
            if "config" in cmd and "init.defaultBranch" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="develop\n", stderr=""
                )
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch(
                "server.tools.worktrees._find_worktree",
                return_value=("/worktree/path", "/repo/path"),
            ),
            patch("server.tools.worktrees.git.list_worktrees", return_value=[]),
            patch("server.tools.worktrees.subprocess.run", side_effect=side_effect),
            patch(
                "server.tools.worktrees.git.rebase_worktree",
                return_value={"status": "rebased", "base_branch": "develop"},
            ),
            patch(
                "server.tools.worktrees.git.merge_ff_only",
                return_value={"status": "merged", "branch": "feature"},
            ),
            patch("server.tools.worktrees.git.remove_worktree"),
        ):
            result = merge_worktree("/worktree/path")  # no base_branch
        data = json.loads(result)
        assert data["result"] != "error"

    def test_both_resolution_methods_fail(self, config_with_repo: Path) -> None:
        """Sites 2+3 (worktrees.py:266-289): both origin/HEAD and
        init.defaultBranch fail -> error JSON."""

        def side_effect(cmd, *args, **kwargs):
            if "symbolic-ref" in cmd and "refs/remotes/origin/HEAD" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            if "symbolic-ref" in cmd and "HEAD" in cmd:
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="refs/heads/feature\n", stderr=""
                )
            if "config" in cmd and "init.defaultBranch" in cmd:
                return subprocess.CompletedProcess(args=cmd, returncode=1, stdout="", stderr="")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

        with (
            patch(
                "server.tools.worktrees._find_worktree",
                return_value=("/worktree/path", "/repo/path"),
            ),
            patch("server.tools.worktrees.git.list_worktrees", return_value=[]),
            patch("server.tools.worktrees.subprocess.run", side_effect=side_effect),
        ):
            result = merge_worktree("/worktree/path")  # no base_branch
        data = json.loads(result)
        assert data["result"] == "error"
        assert "Cannot determine default branch" in data["message"]

    def test_base_branch_resolution_file_not_found(self, config_with_repo: Path) -> None:
        """Site 2 (worktrees.py:290): FileNotFoundError during
        resolution -> error JSON with 'git not found'."""
        call_count = 0

        def side_effect(cmd, *args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # First call: symbolic-ref HEAD → success
                return subprocess.CompletedProcess(
                    args=cmd, returncode=0, stdout="refs/heads/feature\n", stderr=""
                )
            # Second call: origin HEAD resolution → FileNotFoundError
            raise FileNotFoundError("No such file or directory: 'git'")

        with (
            patch(
                "server.tools.worktrees._find_worktree",
                return_value=("/worktree/path", "/repo/path"),
            ),
            patch("server.tools.worktrees.git.list_worktrees", return_value=[]),
            patch("server.tools.worktrees.subprocess.run", side_effect=side_effect),
        ):
            result = merge_worktree("/worktree/path")  # no base_branch
        data = json.loads(result)
        assert data["result"] == "error"
        assert "git not found" in data["message"]

    # --- Tests documenting missing post-commit cleanliness verification ---

    def test_no_post_commit_status_check(self, tmp_path: Path) -> None:
        """status_porcelain is only called once (pre-commit), never post-commit.

        GAP: After a successful commit, auto_commit should call
        status_porcelain a second time to verify the tree is actually clean.
        Currently it does not, so dirty post-commit state goes undetected.
        """
        wt = tmp_path / "wt"
        wt.mkdir()
        # side_effect: first call returns dirty (triggers add/commit path),
        # second value would show leftover changes -- but it's never consumed.
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch(
                "server.tools.worktrees.git.status_porcelain",
                side_effect=["M file.py\n", "M leftover.py\n"],
            ) as mock_status,
            patch("server.tools.worktrees.git.add_all"),
            patch("server.tools.worktrees.git.commit", return_value="abc1234"),
        ):
            result = auto_commit(str(wt), "test commit")
        data = json.loads(result)
        # Current behavior: reports success even though tree would still be dirty
        assert data["result"] == "auto-committed"
        assert data["committed"] is True
        # Only one status_porcelain call -- no post-commit verification
        assert mock_status.call_count == 1

    def test_race_condition_file_created_during_commit(self, tmp_path: Path) -> None:
        """Files created between add and commit are invisible to auto_commit.

        GAP: If a file appears after git add -A but before/after git commit,
        auto_commit returns success with no indication of remaining dirty state.
        A post-commit status_porcelain check would catch this.
        """
        wt = tmp_path / "wt"
        wt.mkdir()
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch(
                "server.tools.worktrees.git.status_porcelain",
                side_effect=["M file.py\n", "?? race_file.py\n"],
            ) as mock_status,
            patch("server.tools.worktrees.git.add_all"),
            patch("server.tools.worktrees.git.commit", return_value="def5678"),
        ):
            result = auto_commit(str(wt))
        data = json.loads(result)
        # Current behavior: success reported, race_file.py is silently missed
        assert data["result"] == "auto-committed"
        assert data["committed"] is True
        assert data["files_committed"] == 1
        # No second call to status_porcelain
        assert mock_status.call_count == 1
        # The response has no field indicating remaining uncommitted changes
        assert "remaining_files" not in data

    def test_partial_add_leaves_unstaged_changes(self, tmp_path: Path) -> None:
        """add_all succeeds but some changes remain unstaged (e.g. gitignored).

        GAP: If git add -A doesn't stage everything (gitignored files, submodule
        dirty state), commit succeeds for the staged subset but auto_commit
        reports the original file_count as files_committed, which may overcount.
        A post-commit status check would reveal the discrepancy.
        """
        wt = tmp_path / "wt"
        wt.mkdir()
        # Pre-commit status shows 3 files, but one is gitignored so add_all
        # only stages 2.  commit succeeds for those 2.
        status_output = "M tracked1.py\nM tracked2.py\n?? ignored.log\n"
        with (
            patch("server.tools.worktrees.git.is_git_repo", return_value=True),
            patch(
                "server.tools.worktrees.git.status_porcelain",
                side_effect=[status_output, "?? ignored.log\n"],
            ) as mock_status,
            patch("server.tools.worktrees.git.add_all"),
            patch("server.tools.worktrees.git.commit", return_value="ccc3333"),
        ):
            result = auto_commit(str(wt))
        data = json.loads(result)
        # Current behavior: reports all 3 files as committed even though
        # ignored.log was never staged.  No post-commit check to catch this.
        assert data["result"] == "auto-committed"
        assert data["files_committed"] == 3  # overcounts -- should be 2
        assert mock_status.call_count == 1


# ---------------------------------------------------------------------------
# wt_rebase_continue tool tests
# ---------------------------------------------------------------------------


class TestRebaseContinueWorktree:
    def test_worktree_not_found(self, config_with_repo: Path) -> None:
        """Non-existent path -> error."""
        with patch("server.tools.worktrees.git.list_worktrees", return_value=_SAMPLE_ENTRIES):
            result = rebase_continue_worktree("/does/not/exist")
        data = json.loads(result)
        assert data["result"] == "error"
        assert "No managed worktree" in data["message"]

    def test_no_rebase_in_progress(self, config_with_repo: Path) -> None:
        """is_rebase_in_progress=False -> error."""
        with (
            patch(
                "server.tools.worktrees._find_worktree",
                return_value=("/worktree/path", "/repo/path"),
            ),
            patch("server.tools.worktrees.git.is_rebase_in_progress", return_value=False),
        ):
            result = rebase_continue_worktree("/worktree/path")
        data = json.loads(result)
        assert data["result"] == "error"
        assert "No rebase in progress" in data["message"]

    def test_success_merged(self, config_with_repo: Path) -> None:
        """Full success: rebase_continue + merge_ff_only both succeed -> merged."""
        with (
            patch(
                "server.tools.worktrees._find_worktree",
                return_value=("/worktree/path", "/repo/path"),
            ),
            patch("server.tools.worktrees.git.is_rebase_in_progress", return_value=True),
            patch(
                "server.tools.worktrees.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "-C", "/worktree/path", "symbolic-ref", "HEAD"],
                    returncode=0,
                    stdout="refs/heads/feature/my-branch\n",
                    stderr="",
                ),
            ),
            patch(
                "server.tools.worktrees.git.rebase_continue",
                return_value={"status": "rebased"},
            ),
            patch(
                "server.tools.worktrees.git.merge_ff_only",
                return_value={"status": "merged", "branch": "feature/my-branch"},
            ),
        ):
            result = rebase_continue_worktree("/worktree/path")
        data = json.loads(result)
        assert data["result"] == "merged"
        assert data["branch"] == "feature/my-branch"
        assert data["worktree_path"] == "/worktree/path"

    def test_continue_still_conflicted(self, config_with_repo: Path) -> None:
        """rebase_continue raises GitConflictError -> conflict result with files."""
        from server.lib.git import GitConflictError

        with (
            patch(
                "server.tools.worktrees._find_worktree",
                return_value=("/worktree/path", "/repo/path"),
            ),
            patch("server.tools.worktrees.git.is_rebase_in_progress", return_value=True),
            patch(
                "server.tools.worktrees.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "-C", "/worktree/path", "symbolic-ref", "HEAD"],
                    returncode=0,
                    stdout="refs/heads/feature\n",
                    stderr="",
                ),
            ),
            patch(
                "server.tools.worktrees.git.rebase_continue",
                side_effect=GitConflictError("still conflicted: still.txt"),
            ),
            patch(
                "server.tools.worktrees.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout="refs/heads/feature\n",
                    stderr="",
                ),
            ),
        ):
            # Patch subprocess.run once for symbolic-ref, then for diff
            def run_side_effect(cmd, *args, **kwargs):
                cmd_list = list(cmd)
                if "symbolic-ref" in cmd_list:
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=0, stdout="refs/heads/feature\n", stderr=""
                    )
                if "--diff-filter=U" in cmd_list:
                    return subprocess.CompletedProcess(
                        args=cmd, returncode=0, stdout="still.txt\n", stderr=""
                    )
                return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

            with (
                patch(
                    "server.tools.worktrees._find_worktree",
                    return_value=("/worktree/path", "/repo/path"),
                ),
                patch("server.tools.worktrees.git.is_rebase_in_progress", return_value=True),
                patch("server.tools.worktrees.subprocess.run", side_effect=run_side_effect),
                patch(
                    "server.tools.worktrees.git.rebase_continue",
                    side_effect=GitConflictError("conflicts remain"),
                ),
            ):
                result = rebase_continue_worktree("/worktree/path")
        data = json.loads(result)
        assert data["result"] == "conflict"
        assert "conflicted_files" in data

    def test_ff_only_failed(self, config_with_repo: Path) -> None:
        """rebase_continue succeeds but merge_ff_only fails -> ff_only_failed."""
        with (
            patch(
                "server.tools.worktrees._find_worktree",
                return_value=("/worktree/path", "/repo/path"),
            ),
            patch("server.tools.worktrees.git.is_rebase_in_progress", return_value=True),
            patch(
                "server.tools.worktrees.subprocess.run",
                return_value=subprocess.CompletedProcess(
                    args=["git", "-C", "/worktree/path", "symbolic-ref", "HEAD"],
                    returncode=0,
                    stdout="refs/heads/feature\n",
                    stderr="",
                ),
            ),
            patch(
                "server.tools.worktrees.git.rebase_continue",
                return_value={"status": "rebased"},
            ),
            patch(
                "server.tools.worktrees.git.merge_ff_only",
                side_effect=GitError("not a fast-forward"),
            ),
        ):
            result = rebase_continue_worktree("/worktree/path")
        data = json.loads(result)
        assert data["result"] == "ff_only_failed"
        assert data["branch"] == "feature"
