"""Subprocess-based git worktree wrapper.

Uses `git worktree --porcelain` for machine-readable output.
All operations are side-effect-free reads except create/remove/prune/lock/unlock.
"""

from __future__ import annotations

import logging
import os
import subprocess
import time
from pathlib import Path

from server.lib.models import WorktreeEntry

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Raised when a git command fails."""


class GitConflictError(GitError):
    """Raised when a git rebase encounters conflicts."""


def _run(
    args: list[str],
    cwd: str | None = None,
    *,
    env: dict[str, str] | None = None,
    stdin: int | None = None,
    error_includes_stdout: bool = False,
) -> str:
    """Run a git command and return stdout. Raises GitError on failure.

    Optional kw-only params:
    - env: env dict for subprocess (default: inherit parent env)
    - stdin: stdin file-descriptor (e.g. ``subprocess.DEVNULL`` for non-interactive
      invocations like ``commit`` w/ pre-commit hooks)
    - error_includes_stdout: when True, GitError message falls back to stdout
      on empty stderr — used by ``commit`` since pre-commit hooks print hook
      progress to stdout, not stderr.
    """
    result = subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=env,
        stdin=stdin,
    )
    if result.returncode != 0:
        if error_includes_stdout:
            detail = (
                result.stderr.strip()
                or result.stdout.strip()
                or f"git {args[0]} failed (rc={result.returncode})"
            )
        else:
            detail = result.stderr.strip() or f"git {args[0]} failed"
        raise GitError(detail)
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


def commit(path: Path, message: str, skip_hooks: bool = False) -> str:
    """Commit staged changes and return the new HEAD SHA.

    Subprocess is invoked with explicit ``cwd``, ``stdin=DEVNULL``, and an env
    that pins ``UV_CACHE_DIR`` to an absolute path inside ``path`` when not
    already set. This matches the behavior of an interactive ``git commit``
    invocation and keeps pre-commit hooks (which resolve relative cache dirs
    against their own cwd) deterministic regardless of where the parent
    process (e.g. an MCP server) was launched from.

    Setting ``skip_hooks=True`` adds ``--no-verify`` as a last-resort bypass
    for environments where pre-commit hooks are broken or unavailable.
    """
    args = ["-C", str(path), "commit", "-m", message]
    if skip_hooks:
        args.append("--no-verify")

    env = os.environ.copy()
    # Pin UV_CACHE_DIR to an absolute path inside the worktree so pre-commit
    # hooks like the per-plugin basedpyright iterator (which defaults to
    # ``${UV_CACHE_DIR:-.uv-cache}``) don't resolve a relative path against an
    # unexpected cwd. No-op if caller already set an absolute UV_CACHE_DIR.
    cur = env.get("UV_CACHE_DIR", "")
    if not cur or not Path(cur).is_absolute():
        env["UV_CACHE_DIR"] = str((path / ".uv-cache").resolve())

    _run(
        args,
        cwd=str(path),
        env=env,
        stdin=subprocess.DEVNULL,
        error_includes_stdout=True,
    )
    return _run(["-C", str(path), "rev-parse", "HEAD"]).strip()


def _resolve_base_ref(repo_path: str, base_branch: str) -> str:
    """Resolve base_branch to a concrete ref, preferring local refs/heads over origin/.

    Returns the ref expression (unchanged input if it already resolves, else
    refs/remotes/origin/<name> if only the remote exists). Raises GitError if
    neither local nor remote ref exists.
    """
    # Prefer local branch
    local = subprocess.run(
        ["git", "-C", repo_path, "show-ref", "--verify", "--quiet", f"refs/heads/{base_branch}"],
        capture_output=True,
        text=True,
    )
    if local.returncode == 0:
        return f"refs/heads/{base_branch}"
    # Fall back to origin/<name>
    remote = subprocess.run(
        [
            "git",
            "-C",
            repo_path,
            "show-ref",
            "--verify",
            "--quiet",
            f"refs/remotes/origin/{base_branch}",
        ],
        capture_output=True,
        text=True,
    )
    if remote.returncode == 0:
        return f"refs/remotes/origin/{base_branch}"
    raise GitError(f"base_branch not found locally or on origin: {base_branch}")


def _is_ancestor(worktree_path: str, ancestor: str, descendant: str) -> bool:
    """Return True if *ancestor* is an ancestor of (or equal to) *descendant*."""
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        capture_output=True,
        text=True,
        cwd=worktree_path,
    )
    return result.returncode == 0


def rebase_worktree(
    repo_path: str, worktree_path: str, base_branch: str
) -> dict[str, str | list[str]]:
    """Rebase the worktree's branch onto base_branch.

    If the worktree HEAD is already a descendant of base_branch (i.e. a linear
    fast-forward is possible), returns {"status": "up_to_date", "base_branch": ...}
    without invoking rebase. This avoids git's default fork-point heuristic, which
    can incorrectly rewind a branch onto an ancient commit when the local reflog
    of base_branch has stale entries (todo 654).

    On conflict, returns {"status": "conflict", "conflicted_files": [...], "base_branch": ...}.
    On non-conflict failure, aborts the rebase and raises GitError.
    On success, returns {"status": "rebased", "base_branch": ...}.
    """
    try:
        # Resolve base_branch to a concrete ref (prefer local over origin/).
        base_ref = _resolve_base_ref(repo_path, base_branch)

        # Short-circuit: if HEAD already contains base_ref, no rebase is needed.
        # This is the fast-forward-eligible case — git rebase with default fork-point
        # can misbehave here (todo 654), so skip it entirely.
        if _is_ancestor(worktree_path, base_ref, "HEAD"):
            return {"status": "up_to_date", "base_branch": base_branch}

        # Pass --no-fork-point to avoid reflog-based surprises when the worktree's
        # view of base_branch has stale reflog entries.
        result = subprocess.run(
            ["git", "rebase", "--no-fork-point", base_ref],
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


def merge_ff_only(
    repo_path: str,
    branch: str,
    worktree_path: str | None = None,
    base_branch: str = "dev",
) -> dict[str, str]:
    """Atomically FF-merge `branch` into `base_branch` of `repo_path`.

    When `worktree_path` is provided, uses `git update-ref` CAS from the worktree
    to avoid the multi-worktree race in `git merge --ff-only`. Per todo 735.

    The CAS loop:
    - Reads current base_branch ref value (old_sha).
    - Verifies branch is FF-mergeable (merge-base --is-ancestor).
    - Reads branch tip (new_sha).
    - Atomically updates refs/heads/<base_branch> from old_sha to new_sha.
    - Retries up to 5 times with exponential backoff on CAS conflict.

    After a successful ref update, syncs base repo's index/working tree via
    `git reset --keep HEAD` (safe: aborts if it would discard uncommitted work).
    If reset --keep fails, logs a warning and continues — the ref is already
    updated and the user can sync manually.

    Falls back to legacy `git merge --ff-only` when worktree_path is None
    (backward-compatible for callers that don't supply it).

    Raises GitError if not FF-mergeable or max retries exhausted.
    """
    if worktree_path is None:
        # Legacy path: kept for backward-compat; no CAS protection.
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

    # Atomic CAS path.
    MAX_RETRIES = 5
    BACKOFF_MS = [10, 20, 40, 80, 160]
    new_sha: str = ""
    last_err: str = ""

    try:
        for attempt in range(MAX_RETRIES):
            # Read current base_branch ref value.
            rev_result = subprocess.run(
                ["git", "rev-parse", f"refs/heads/{base_branch}"],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            )
            if rev_result.returncode != 0:
                raise GitError(
                    f"failed to read refs/heads/{base_branch}: {rev_result.stderr.strip()}"
                )
            old_sha = rev_result.stdout.strip()

            # Verify branch is FF-mergeable onto current base_branch.
            ancestor_result = subprocess.run(
                ["git", "merge-base", "--is-ancestor", old_sha, branch],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            )
            if ancestor_result.returncode != 0:
                raise GitError(
                    f"Fast-forward merge failed for branch {branch}: "
                    f"{branch} is not a fast-forward of {base_branch} ({old_sha})"
                )

            # Read branch tip.
            tip_result = subprocess.run(
                ["git", "rev-parse", branch],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            )
            if tip_result.returncode != 0:
                raise GitError(f"failed to read branch {branch}: {tip_result.stderr.strip()}")
            new_sha = tip_result.stdout.strip()

            # Atomic CAS: only succeeds if base_branch ref still equals old_sha.
            cas_result = subprocess.run(
                ["git", "update-ref", f"refs/heads/{base_branch}", new_sha, old_sha],
                cwd=worktree_path,
                capture_output=True,
                text=True,
            )
            if cas_result.returncode == 0:
                break  # CAS succeeded.
            last_err = cas_result.stderr.strip() or "<unknown>"
            # CAS failed (another caller updated the ref) — retry after backoff.
            if attempt < MAX_RETRIES - 1:
                time.sleep(BACKOFF_MS[attempt] / 1000.0)
        else:
            raise GitError(
                f"max retries exhausted on CAS update-ref refs/heads/{base_branch}; "
                f"last error: {last_err}"
            )
    except FileNotFoundError as err:
        raise GitError(f"git not found or invalid path: {worktree_path}") from err

    # Sync base repo's index and working tree to the new HEAD.
    # After CAS the ref changed but the base repo's index + working tree still reflect
    # the old HEAD. We need to advance them.
    #
    # Strategy: check if the working tree has any unstaged modifications (git diff --quiet,
    # compares working tree to index). If clean, safe to hard-reset. If dirty, use
    # reset --keep which preserves unstaged work but aborts if the new HEAD would
    # conflict with it.
    #
    # Note: `git diff --cached` is NOT used here because the index still reflects the
    # old HEAD — after CAS the staged-vs-HEAD diff always shows differences until synced.
    wt_dirty_check = subprocess.run(
        ["git", "diff", "--quiet"],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )
    # returncode 0 = working tree matches index (clean), 1 = unstaged changes exist
    wt_is_clean = wt_dirty_check.returncode == 0

    if wt_is_clean:
        # Fast path: hard reset advances index + working tree to new HEAD.
        sync_result = subprocess.run(
            ["git", "reset", "--hard", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )
    else:
        # Dirty path: keep preserves unstaged work; aborts on conflict with new HEAD.
        sync_result = subprocess.run(
            ["git", "reset", "--keep", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
        )

    if sync_result.returncode != 0:
        logger.warning(
            "merge_ff_only: base repo %s has uncommitted work conflicting with new HEAD; "
            "refs/heads/%s already updated to %s. User must sync working tree manually. "
            "stderr: %s",
            repo_path,
            base_branch,
            new_sha,
            sync_result.stderr.strip(),
        )

    return {"status": "merged", "branch": branch}
