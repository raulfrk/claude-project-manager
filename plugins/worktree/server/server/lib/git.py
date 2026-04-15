"""Subprocess-based git worktree wrapper.

Uses `git worktree --porcelain` for machine-readable output.
All operations are side-effect-free reads except create/remove/prune/lock/unlock.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from server.lib.models import WorktreeEntry

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Raised when a git command fails."""


class GitConflictError(GitError):
    """Raised when a git rebase encounters conflicts."""


def _run(args: list[str], cwd: str | None = None) -> str:
    """Run a git command and return stdout. Raises GitError on failure."""
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    if result.returncode != 0:
        raise GitError(result.stderr.strip() or f"git {args[0]} failed")
    return result.stdout


def list_worktrees(repo_path: str) -> list[WorktreeEntry]:
    """List all worktrees for a repository using --porcelain format."""
    output = _run(["worktree", "list", "--porcelain"], cwd=repo_path)
    return _parse_porcelain(output)


def _parse_porcelain(output: str) -> list[WorktreeEntry]:
    """Parse `git worktree list --porcelain` output into WorktreeEntry objects."""
    entries: list[WorktreeEntry] = []
    current: dict[str, str | bool] = {}

    for line in output.splitlines():
        if line == "":
            if current:
                entries.append(_dict_to_entry(current))
                current = {}
        elif line.startswith("worktree "):
            current["path"] = line[len("worktree ") :]
        elif line.startswith("HEAD "):
            current["head"] = line[len("HEAD ") :]
        elif line.startswith("branch "):
            current["branch"] = line[len("branch ") :]
        elif line == "bare":
            current["bare"] = True
        elif line == "detached":
            current["detached"] = True
        elif line.startswith("locked"):
            current["locked"] = True
        elif line.startswith("prunable"):
            current["prunable"] = True

    if current:
        entries.append(_dict_to_entry(current))

    return entries


def _dict_to_entry(d: dict[str, str | bool]) -> WorktreeEntry:
    return WorktreeEntry(
        path=str(d.get("path", "")),
        branch=str(d.get("branch", "detached")),
        head=str(d.get("head", "")),
        bare=bool(d.get("bare", False)),
        detached=bool(d.get("detached", False)),
        locked=bool(d.get("locked", False)),
        prunable=bool(d.get("prunable", False)),
    )


def add_worktree(repo_path: str, worktree_path: str, branch: str, new_branch: bool = True) -> str:
    """Create a new worktree.

    If new_branch=True, creates a new branch (-b <branch> <path>).
    If new_branch=False, checks out an existing branch (<path> <commit-ish>).
    Returns the created worktree path.
    """
    Path(worktree_path).parent.mkdir(parents=True, exist_ok=True)
    if new_branch:
        args = ["worktree", "add", "-b", branch, worktree_path]
    else:
        args = ["worktree", "add", worktree_path, branch]
    _run(args, cwd=repo_path)
    return worktree_path


def reset_hard(worktree_path: str) -> str:
    """Run `git reset --hard HEAD` in a worktree. Raises GitError on failure."""
    return _run(["reset", "--hard", "HEAD"], cwd=worktree_path)


def clean_untracked(worktree_path: str) -> str:
    """Run `git clean -fd` in a worktree. Raises GitError on failure."""
    return _run(["clean", "-fd"], cwd=worktree_path)


def remove_worktree(repo_path: str, worktree_path: str, force: bool = False) -> None:
    """Remove a worktree. Use force=True for unclean or locked worktrees."""
    args = ["worktree", "remove"]
    if force:
        # Double --force is required to remove locked worktrees
        args.extend(["--force", "--force"])
    args.append(worktree_path)
    _run(args, cwd=repo_path)


def prune_worktrees(repo_path: str) -> str:
    """Prune stale worktree admin files."""
    return _run(["worktree", "prune", "--verbose"], cwd=repo_path)


def lock_worktree(repo_path: str, worktree_path: str, reason: str = "") -> None:
    """Lock a worktree to prevent pruning."""
    args = ["worktree", "lock"]
    if reason:
        args += ["--reason", reason]
    args.append(worktree_path)
    _run(args, cwd=repo_path)


def unlock_worktree(repo_path: str, worktree_path: str) -> None:
    """Unlock a previously locked worktree."""
    _run(["worktree", "unlock", worktree_path], cwd=repo_path)


def is_git_repo(path: str) -> bool:
    """Return True if path is inside a git repository."""
    try:
        _run(["rev-parse", "--git-dir"], cwd=path)
        return True
    except GitError:
        return False


def status_porcelain(path: Path) -> str:
    """Return `git status --porcelain` output. Empty string means clean."""
    return _run(["-C", str(path), "status", "--porcelain"])


def add_all(path: Path) -> None:
    """Stage all changes (tracked and untracked)."""
    _run(["-C", str(path), "add", "-A"])


def commit(path: Path, message: str) -> str:
    """Commit staged changes and return the new HEAD SHA."""
    _run(["-C", str(path), "commit", "-m", message])
    return _run(["-C", str(path), "rev-parse", "HEAD"]).strip()


def rebase_worktree(
    repo_path: str, worktree_path: str, base_branch: str
) -> dict[str, str | list[str]]:
    """Rebase the worktree's branch onto base_branch.

    On conflict, returns {"status": "conflict", "conflicted_files": [...], "base_branch": ...}.
    On non-conflict failure, aborts the rebase and raises GitError.
    On success, returns {"status": "rebased", "base_branch": ...}.
    """
    try:
        result = subprocess.run(
            ["git", "rebase", base_branch],
            capture_output=True,
            text=True,
            cwd=worktree_path,
        )
        if result.returncode != 0:
            # Check if this is a conflict
            diff_result = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                capture_output=True,
                text=True,
                cwd=worktree_path,
            )
            conflicted_files = (
                diff_result.stdout.strip().splitlines() if diff_result.returncode == 0 else []
            )
            if conflicted_files:
                return {
                    "status": "conflict",
                    "conflicted_files": conflicted_files,
                    "base_branch": base_branch,
                }
            # Non-conflict failure — abort and propagate original error
            stderr = result.stderr.strip()
            try:
                subprocess.run(
                    ["git", "rebase", "--abort"],
                    capture_output=True,
                    text=True,
                    cwd=worktree_path,
                )
            except Exception as abort_err:
                logger.warning("git rebase --abort also failed: %s", abort_err)
            raise GitError(f"Rebase failed in {worktree_path}: {stderr}")
    except FileNotFoundError as err:
        raise GitError(f"git not found or invalid path: {worktree_path}") from err
    return {"status": "rebased", "base_branch": base_branch}


def rebase_abort(worktree_path: str) -> None:
    """Abort an in-progress rebase."""
    _run(["rebase", "--abort"], cwd=worktree_path)


def is_rebase_in_progress(worktree_path: str) -> bool:
    """Return True if a rebase is currently in progress in the worktree."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--git-dir"],
            capture_output=True,
            text=True,
            cwd=worktree_path,
        )
        if result.returncode != 0:
            return False
        git_dir_str = result.stdout.strip()
        git_dir = Path(git_dir_str)
        if not git_dir.is_absolute():
            git_dir = Path(worktree_path) / git_dir
        return (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists()
    except (FileNotFoundError, OSError):
        return False


def rebase_continue(worktree_path: str) -> dict[str, str]:
    """Stage all changes and continue an in-progress rebase.

    Returns {"status": "rebased"} on success.
    Raises GitConflictError if conflicts remain after continue.
    Raises GitError on other failures.
    """
    # Stage all changes
    add_result = subprocess.run(
        ["git", "add", "-A"],
        capture_output=True,
        text=True,
        cwd=worktree_path,
    )
    if add_result.returncode != 0:
        raise GitError(f"git add -A failed in {worktree_path}: {add_result.stderr.strip()}")

    # Continue rebase with non-interactive editor
    continue_result = subprocess.run(
        ["git", "rebase", "--continue"],
        capture_output=True,
        text=True,
        cwd=worktree_path,
        env={**os.environ, "GIT_EDITOR": "true"},
    )
    if continue_result.returncode != 0:
        # Check for remaining conflicts
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True,
            text=True,
            cwd=worktree_path,
        )
        conflicted_files = (
            diff_result.stdout.strip().splitlines() if diff_result.returncode == 0 else []
        )
        if conflicted_files:
            raise GitConflictError(
                f"Conflicts remain after rebase --continue in {worktree_path}: "
                + ", ".join(conflicted_files)
            )
        raise GitError(
            f"git rebase --continue failed in {worktree_path}: " + continue_result.stderr.strip()
        )
    return {"status": "rebased"}


def merge_ff_only(repo_path: str, branch: str) -> dict[str, str]:
    """Fast-forward merge a branch into the current branch at repo_path."""
    try:
        result = subprocess.run(
            ["git", "merge", "--ff-only", branch],
            capture_output=True,
            text=True,
            cwd=repo_path,
        )
        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise GitError(f"Fast-forward merge failed for branch {branch}: {stderr}")
    except FileNotFoundError as err:
        raise GitError(f"git not found or invalid path: {repo_path}") from err
    return {"status": "merged", "branch": branch}
