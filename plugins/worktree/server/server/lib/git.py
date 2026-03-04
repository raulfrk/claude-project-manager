"""Subprocess-based git worktree wrapper.

Uses `git worktree --porcelain` for machine-readable output.
All operations are side-effect-free reads except create/remove/prune/lock/unlock.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from server.lib.models import WorktreeEntry


class GitError(Exception):
    """Raised when a git command fails."""


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


def remove_worktree(repo_path: str, worktree_path: str, force: bool = False) -> None:
    """Remove a worktree. Use force=True only for unclean worktrees."""
    args = ["worktree", "remove"]
    if force:
        args.append("--force")
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
