"""MCP tools for git worktree CRUD operations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import git, storage
from server.lib.git import GitError
from server.tools.repos import get_repo

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _resolve_worktree_path(repo_label: str, branch: str, custom_path: str | None) -> str:
    """Resolve the target path for a new worktree."""
    if custom_path:
        return str(Path(custom_path).expanduser().resolve())
    config = storage.load()
    base = Path(config.default_worktree_dir).expanduser()
    return str(base / repo_label / branch.replace("/", "-"))


def create_worktree(
    repo_label: str,
    branch: str,
    path: str | None = None,
    new_branch: bool = True,
) -> str:
    """Create a worktree from a registered base repo."""
    repo = get_repo(repo_label)
    if repo is None:
        return f"Error: no repo with label '{repo_label}'. Run /worktree:add-repo first."

    worktree_path = _resolve_worktree_path(repo_label, branch, path)
    if Path(worktree_path).exists():
        return f"Error: path already exists: {worktree_path}"

    try:
        git.add_worktree(repo.path, worktree_path, branch, new_branch=new_branch)
    except GitError as e:
        return f"Error: {e}"

    return f"Created worktree at {worktree_path} (branch: {branch}, repo: {repo_label})."


def list_worktrees(repo_label: str | None = None) -> str:
    """List worktrees for one or all configured repos."""
    config = storage.load()
    repos = config.base_repos
    if repo_label:
        repos = [r for r in repos if r.label == repo_label]
        if not repos:
            return f"No repo with label '{repo_label}'."

    if not repos:
        return "No base repos configured."

    lines: list[str] = []
    for repo in repos:
        try:
            entries = git.list_worktrees(repo.path)
        except GitError as e:
            lines.append(f"[{repo.label}] Error: {e}")
            continue
        lines.append(f"[{repo.label}] {repo.path} — {len(entries)} worktree(s):")
        for entry in entries:
            status = " [locked]" if entry.locked else ""
            status += " [prunable]" if entry.prunable else ""
            lines.append(f"  {entry.path}  branch={entry.branch}  head={entry.head[:8]}{status}")

    return "\n".join(lines) if lines else "No worktrees found."


def get_worktree(path: str) -> str:
    """Get details of a specific worktree by path."""
    config = storage.load()
    for repo in config.base_repos:
        try:
            entries = git.list_worktrees(repo.path)
        except GitError:
            continue
        for entry in entries:
            if entry.path == str(Path(path).expanduser().resolve()):
                return json.dumps(entry.to_dict(), indent=2)
    return f"No worktree found at: {path}"


def remove_worktree(path: str, force: bool = False) -> str:
    """Remove a worktree by path."""
    abs_path = str(Path(path).expanduser().resolve())
    config = storage.load()

    # Find which repo owns this worktree
    for repo in config.base_repos:
        try:
            entries = git.list_worktrees(repo.path)
        except GitError:
            continue
        if any(e.path == abs_path for e in entries):
            try:
                git.remove_worktree(repo.path, abs_path, force=force)
                return f"Removed worktree at {abs_path}."
            except GitError as e:
                return f"Error: {e}\nTip: use force=true for unclean worktrees."

    return f"No managed worktree found at: {abs_path}"


def prune_worktrees(repo_label: str | None = None) -> str:
    """Prune stale worktree admin files."""
    config = storage.load()
    repos = config.base_repos
    if repo_label:
        repos = [r for r in repos if r.label == repo_label]

    results: list[str] = []
    for repo in repos:
        try:
            output = git.prune_worktrees(repo.path)
            results.append(f"[{repo.label}] {output.strip() or 'Nothing to prune.'}")
        except GitError as e:
            results.append(f"[{repo.label}] Error: {e}")

    return "\n".join(results) if results else "No repos configured."


def lock_worktree(path: str, reason: str = "") -> str:
    """Lock a worktree to prevent pruning."""
    abs_path = str(Path(path).expanduser().resolve())
    config = storage.load()
    for repo in config.base_repos:
        try:
            entries = git.list_worktrees(repo.path)
        except GitError:
            continue
        if any(e.path == abs_path for e in entries):
            try:
                git.lock_worktree(repo.path, abs_path, reason=reason)
                return f"Locked worktree at {abs_path}."
            except GitError as e:
                return f"Error: {e}"
    return f"No managed worktree found at: {abs_path}"


def unlock_worktree(path: str) -> str:
    """Unlock a worktree."""
    abs_path = str(Path(path).expanduser().resolve())
    config = storage.load()
    for repo in config.base_repos:
        try:
            entries = git.list_worktrees(repo.path)
        except GitError:
            continue
        if any(e.path == abs_path for e in entries):
            try:
                git.unlock_worktree(repo.path, abs_path)
                return f"Unlocked worktree at {abs_path}."
            except GitError as e:
                return f"Error: {e}"
    return f"No managed worktree found at: {abs_path}"


def register(app: FastMCP) -> None:
    """Register worktree tools with the MCP application."""

    @app.tool(description="Create a worktree from a registered base repo.")
    def wt_create(
        repo_label: str,
        branch: str,
        path: str | None = None,
        new_branch: bool = True,
    ) -> str:
        return create_worktree(repo_label, branch, path, new_branch)

    @app.tool(description="List worktrees for one or all configured repos.")
    def wt_list(repo_label: str | None = None) -> str:
        return list_worktrees(repo_label)

    @app.tool(description="Get details of a specific worktree by path.")
    def wt_get(path: str) -> str:
        return get_worktree(path)

    @app.tool(description="Remove a worktree by path.")
    def wt_remove(path: str, force: bool = False) -> str:
        return remove_worktree(path, force)

    @app.tool(description="Prune stale worktree admin files.")
    def wt_prune(repo_label: str | None = None) -> str:
        return prune_worktrees(repo_label)

    @app.tool(description="Lock a worktree to prevent pruning or deletion.")
    def wt_lock(path: str, reason: str = "") -> str:
        return lock_worktree(path, reason)

    @app.tool(description="Unlock a previously locked worktree.")
    def wt_unlock(path: str) -> str:
        return unlock_worktree(path)
