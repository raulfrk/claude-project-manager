"""MCP tools for git worktree CRUD operations."""

from __future__ import annotations

import contextlib
import json
import logging
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import git, storage
from server.lib.git import GitConflictError, GitError
from server.tools.repos import get_repo

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


logger = logging.getLogger(__name__)


def _find_worktree(path: str) -> tuple[str, str] | None:
    """Find a worktree by path across all repos. Returns (abs_path, repo_path) or None."""
    abs_path = str(Path(path).expanduser().resolve())
    config = storage.load()
    if not config.base_repos:
        logger.warning("_find_worktree: no base repos configured")
        return None
    for repo in config.base_repos:
        try:
            entries = git.list_worktrees(repo.path)
        except GitError as exc:
            logger.warning(
                "_find_worktree: git list_worktrees failed for repo %s: %s",
                repo.label,
                exc,
                exc_info=True,
            )
            continue
        if any(e.path == abs_path for e in entries):
            return abs_path, repo.path
    logger.warning(
        "_find_worktree: path %s not found in any repo (checked %d repos)",
        abs_path,
        len(config.base_repos),
    )
    return None


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
    if not branch or not branch.strip():
        return json.dumps({"result": "Error: branch name cannot be empty.", "worktree_path": None})
    repo = get_repo(repo_label)
    if repo is None:
        return json.dumps(
            {
                "result": (
                    f"Error: no repo with label '{repo_label}'. Run /worktree:add-repo first."
                ),
                "worktree_path": None,
            }
        )

    worktree_path = _resolve_worktree_path(repo_label, branch, path)

    try:
        git.add_worktree(repo.path, worktree_path, branch, new_branch=new_branch)
    except GitError as exc:
        with contextlib.suppress(Exception):
            git.remove_worktree(repo.path, worktree_path, force=True)
        return json.dumps({"result": f"Error: {exc}", "worktree_path": None})

    # Clean the new worktree so it matches HEAD exactly
    warnings: list[str] = []
    try:
        git.reset_hard(worktree_path)
    except GitError as e:
        warnings.append(f"git reset --hard failed: {e}")
    try:
        git.clean_untracked(worktree_path)
    except GitError as e:
        warnings.append(f"git clean -fd failed: {e}")

    msg = f"Created worktree at {worktree_path} (branch: {branch}, repo: {repo_label})."
    if warnings:
        msg += " Warnings: " + "; ".join(warnings)
    return json.dumps({"result": msg, "worktree_path": worktree_path})


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
            head_display = entry.head[:8] or "(none)"
            lines.append(f"  {entry.path}  branch={entry.branch}  head={head_display}{status}")

    return "\n".join(lines) if lines else "No worktrees found."


def get_worktree(path: str) -> str:
    """Get details of a specific worktree by path."""
    abs_path = str(Path(path).expanduser().resolve())
    result = _find_worktree(path)
    if not result:
        return json.dumps({"error": f"No worktree found at: {abs_path}"})
    abs_path, repo_path = result
    for entry in git.list_worktrees(repo_path):
        if entry.path == abs_path:
            return json.dumps(entry.to_dict(), indent=2)
    return json.dumps({"error": f"No worktree found at: {abs_path}"})


def remove_worktree(path: str, force: bool = False) -> str:
    """Remove a worktree by path."""
    result = _find_worktree(path)
    if not result:
        return json.dumps(
            {"result": f"No managed worktree found at: {path}", "worktree_path": None}
        )
    abs_path, repo_path = result
    if not force:
        for entry in git.list_worktrees(repo_path):
            if entry.path == abs_path and entry.locked:
                return json.dumps(
                    {
                        "result": "error",
                        "message": f"Worktree is locked: {abs_path}. "
                        "Unlock first with wt_unlock, or use force=true.",
                        "worktree_path": abs_path,
                    }
                )
    try:
        git.remove_worktree(repo_path, abs_path, force=force)
        return json.dumps({"result": f"Removed worktree at {abs_path}.", "worktree_path": abs_path})
    except GitError as e:
        return json.dumps(
            {
                "result": f"Error: {e}\nTip: use force=true for unclean worktrees.",
                "worktree_path": abs_path,
            }
        )


def prune_worktrees(repo_label: str | None = None) -> str:
    """Prune stale worktree admin files."""
    config = storage.load()
    repos = config.base_repos
    if repo_label:
        repos = [r for r in repos if r.label == repo_label]
        if not repos:
            return f"No repo with label '{repo_label}'."

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
    result = _find_worktree(path)
    if not result:
        return json.dumps({"error": f"No managed worktree found at: {path}"})
    abs_path, repo_path = result
    try:
        git.lock_worktree(repo_path, abs_path, reason=reason)
        return json.dumps({"result": f"Locked worktree at {abs_path}.", "path": abs_path})
    except GitError as exc:
        msg = str(exc).lower()
        if any(s in msg for s in ("not a worktree", "not a working tree", "no such file")):
            return json.dumps(
                {
                    "error": f"Worktree not found (may have been removed): {abs_path}",
                    "path": abs_path,
                }
            )
        return json.dumps({"error": f"Error: {exc}", "path": abs_path})


def unlock_worktree(path: str) -> str:
    """Unlock a worktree."""
    result = _find_worktree(path)
    if not result:
        return json.dumps({"error": f"No managed worktree found at: {path}"})
    abs_path, repo_path = result
    try:
        git.unlock_worktree(repo_path, abs_path)
        return json.dumps({"result": f"Unlocked worktree at {abs_path}.", "path": abs_path})
    except GitError as exc:
        msg = str(exc).lower()
        if any(s in msg for s in ("not a worktree", "not a working tree", "no such file")):
            return json.dumps(
                {
                    "error": f"Worktree not found (may have been removed): {abs_path}",
                    "path": abs_path,
                }
            )
        return json.dumps({"error": f"Error: {exc}", "path": abs_path})


def merge_worktree(path: str, base_branch: str | None = None) -> str:
    """Rebase a worktree onto base_branch, then fast-forward merge into the base repo."""
    result = _find_worktree(path)
    if not result:
        return json.dumps({"result": "error", "message": f"No managed worktree found at: {path}"})
    abs_path, repo_path = result

    # Check if worktree is locked
    for entry in git.list_worktrees(repo_path):
        if entry.path == abs_path and entry.locked:
            return json.dumps({"result": "error", "message": f"Worktree is locked: {abs_path}"})

    # Check if worktree is on a detached HEAD
    try:
        head_ref = subprocess.run(
            ["git", "-C", abs_path, "symbolic-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
        if head_ref.returncode != 0:
            return json.dumps(
                {"result": "error", "message": f"Worktree is in detached HEAD state: {abs_path}"}
            )
        branch_name = head_ref.stdout.strip().removeprefix("refs/heads/")
    except FileNotFoundError:
        return json.dumps(
            {"result": "error", "message": f"git not found or invalid path: {abs_path}"}
        )

    # Resolve base_branch if not provided
    if not base_branch:
        try:
            origin_head = subprocess.run(
                ["git", "-C", repo_path, "symbolic-ref", "refs/remotes/origin/HEAD"],
                capture_output=True,
                text=True,
            )
            if origin_head.returncode == 0:
                base_branch = origin_head.stdout.strip().removeprefix("refs/remotes/origin/")
            else:
                default_branch = subprocess.run(
                    ["git", "-C", repo_path, "config", "init.defaultBranch"],
                    capture_output=True,
                    text=True,
                )
                if default_branch.returncode == 0 and default_branch.stdout.strip():
                    base_branch = default_branch.stdout.strip()
                else:
                    return json.dumps(
                        {
                            "result": "error",
                            "message": (
                                "Cannot determine default branch. Provide base_branch explicitly."
                            ),
                        }
                    )
        except FileNotFoundError:
            return json.dumps(
                {"result": "error", "message": f"git not found or invalid path: {repo_path}"}
            )

    # Rebase worktree onto base_branch
    rebase_result = git.rebase_worktree(repo_path, abs_path, base_branch)
    if rebase_result["status"] == "conflict":
        return json.dumps(
            {
                "result": "conflict",
                "conflicted_files": rebase_result["conflicted_files"],
                "worktree_path": abs_path,
                "branch": branch_name,
            }
        )

    # Fast-forward merge into base repo
    try:
        git.merge_ff_only(repo_path, branch_name, worktree_path=abs_path, base_branch=base_branch)
    except GitError as e:
        return json.dumps(
            {
                "result": "ff_only_failed",
                "message": str(e),
                "worktree_path": abs_path,
                "branch": branch_name,
            }
        )

    return json.dumps(
        {
            "result": "merged",
            "worktree_path": abs_path,
            "branch": branch_name,
            "base_branch": base_branch,
        }
    )


def rebase_continue_worktree(path: str) -> str:
    """Continue an in-progress rebase in a worktree after conflicts are resolved."""
    result = _find_worktree(path)
    if not result:
        return json.dumps({"result": "error", "message": f"No managed worktree found at: {path}"})
    abs_path, repo_path = result

    if not git.is_rebase_in_progress(abs_path):
        return json.dumps({"result": "error", "message": f"No rebase in progress at {abs_path}"})

    # Get branch name
    try:
        head_ref = subprocess.run(
            ["git", "-C", abs_path, "symbolic-ref", "HEAD"],
            capture_output=True,
            text=True,
        )
        if head_ref.returncode != 0:
            return json.dumps(
                {"result": "error", "message": f"Worktree is in detached HEAD state: {abs_path}"}
            )
        branch_name = head_ref.stdout.strip().removeprefix("refs/heads/")
    except FileNotFoundError:
        return json.dumps(
            {"result": "error", "message": f"git not found or invalid path: {abs_path}"}
        )

    # Continue rebase
    try:
        git.rebase_continue(abs_path)
    except GitConflictError:
        diff_result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            capture_output=True,
            text=True,
            cwd=abs_path,
        )
        conflicted_files = (
            diff_result.stdout.strip().splitlines() if diff_result.returncode == 0 else []
        )
        return json.dumps(
            {
                "result": "conflict",
                "conflicted_files": conflicted_files,
                "worktree_path": abs_path,
            }
        )
    except GitError as e:
        return json.dumps({"result": "error", "message": str(e)})

    # Resolve base_branch for CAS merge.
    rebase_base_branch = "dev"
    try:
        origin_head = subprocess.run(
            ["git", "-C", repo_path, "symbolic-ref", "refs/remotes/origin/HEAD"],
            capture_output=True,
            text=True,
        )
        if origin_head.returncode == 0:
            rebase_base_branch = origin_head.stdout.strip().removeprefix("refs/remotes/origin/")
        else:
            default_branch = subprocess.run(
                ["git", "-C", repo_path, "config", "init.defaultBranch"],
                capture_output=True,
                text=True,
            )
            if default_branch.returncode == 0 and default_branch.stdout.strip():
                rebase_base_branch = default_branch.stdout.strip()
    except FileNotFoundError:
        logger.warning(
            "rebase_continue_worktree: failed to read base branch from worktree config; "
            "defaulting to 'dev'. If git is missing, merge_ff_only will surface the error."
        )
        # keep default; merge_ff_only will surface the error

    # Fast-forward merge into base repo
    try:
        git.merge_ff_only(
            repo_path, branch_name, worktree_path=abs_path, base_branch=rebase_base_branch
        )
    except GitError as e:
        return json.dumps(
            {
                "result": "ff_only_failed",
                "message": str(e),
                "worktree_path": abs_path,
                "branch": branch_name,
            }
        )

    return json.dumps(
        {
            "result": "merged",
            "worktree_path": abs_path,
            "branch": branch_name,
        }
    )


def auto_commit(worktree_path: str, message: str = "Auto-commit agent work") -> str:
    """Auto-commit any uncommitted changes in a worktree."""
    path = Path(worktree_path).expanduser().resolve()
    if not path.exists():
        return json.dumps(
            {
                "result": "error",
                "worktree_path": worktree_path,
                "error": f"Path does not exist: {path}",
            }
        )

    if not git.is_git_repo(str(path)):
        return json.dumps(
            {"result": "error", "worktree_path": worktree_path, "error": "Not a git repository"}
        )

    try:
        status = git.status_porcelain(path)
    except GitError as e:
        return json.dumps(
            {"result": "error", "worktree_path": worktree_path, "error": f"git status failed: {e}"}
        )

    if not status.strip():
        return json.dumps(
            {
                "result": "clean",
                "worktree_path": worktree_path,
                "committed": False,
                "files_committed": 0,
                "commit_sha": None,
            }
        )

    file_count = len(status.strip().splitlines())

    try:
        git.add_all(path)
    except GitError as e:
        return json.dumps(
            {"result": "warning", "worktree_path": worktree_path, "error": f"git add failed: {e}"}
        )

    try:
        sha = git.commit(path, message)
    except GitError as e:
        return json.dumps(
            {
                "result": "warning",
                "worktree_path": worktree_path,
                "error": f"git commit failed: {e}",
            }
        )

    return json.dumps(
        {
            "result": "auto-committed",
            "worktree_path": worktree_path,
            "committed": True,
            "files_committed": file_count,
            "commit_sha": sha,
        }
    )


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

    @app.tool(
        description=(
            "Rebase a worktree onto base_branch, then fast-forward merge into the base repo."
        )
    )
    def wt_merge(path: str, base_branch: str | None = None) -> str:
        return merge_worktree(path, base_branch)

    @app.tool(description="Continue an in-progress rebase after resolving conflicts in a worktree.")
    def wt_rebase_continue(path: str) -> str:
        return rebase_continue_worktree(path)

    @app.tool(
        description=(
            "Auto-commit any uncommitted changes in a worktree."
            " Safety net for agents that write files without committing."
        )
    )
    def wt_auto_commit(worktree_path: str, message: str = "Auto-commit agent work") -> str:
        return auto_commit(worktree_path, message)
