"""Git tracking for project tracking directories — auto-commit and optional GitHub push."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import subprocess
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

    from server.lib.models import ProjConfig, ProjectMeta

# Files staged on every flush (explicit — no git add -A to avoid stray YAML leakage)
_FLUSH_FILES = ("data.db", "todos.json", "archive.json", "decisions.json", "proj.yaml")

# Lines to ensure are present in .gitignore for WAL + tmp file suppression
_GITIGNORE_ENTRIES = ("*.tmp", "__pycache__/", "*.pyc", "data.db-wal", "data.db-shm")


def resolve_config(
    cfg: ProjConfig,
    meta: ProjectMeta,
) -> tuple[bool, bool, str]:
    """Resolve effective (enabled, github_enabled, github_repo_format) from global + per-project.

    Per-project values of None fall through to global defaults.
    """
    enabled = (
        meta.git_tracking.enabled
        if meta.git_tracking.enabled is not None
        else cfg.git_tracking.enabled
    )
    github = (
        meta.git_tracking.github_enabled
        if meta.git_tracking.github_enabled is not None
        else cfg.git_tracking.github_enabled
    )
    fmt = (
        meta.git_tracking.github_repo_format
        if meta.git_tracking.github_repo_format is not None
        else cfg.git_tracking.github_repo_format
    )
    return enabled, github, fmt


def _run(cmd: list[str], cwd: str | Path) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr).
    Returns (1, '', 'command not found') if the executable is missing.
    """
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=str(cwd),
            check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except (FileNotFoundError, subprocess.SubprocessError):
        return 1, "", "command not found"


def is_git_repo(tracking_path: Path) -> bool:
    """Check if tracking_path is inside a git repo."""
    rc, _, _ = _run(["git", "rev-parse", "--git-dir"], tracking_path)
    return rc == 0


def ensure_git_repo(tracking_path: Path) -> bool:
    """Initialize a git repo if not already one. Creates/updates .gitignore. Returns True."""
    tracking_path.mkdir(parents=True, exist_ok=True)
    if is_git_repo(tracking_path):
        _ensure_gitignore(tracking_path)
        return True
    rc, _, _ = _run(["git", "init"], tracking_path)
    if rc != 0:
        return False
    _ensure_gitignore(tracking_path)
    return True


def _ensure_gitignore(tracking_path: Path) -> None:
    """Ensure .gitignore contains all required entries. Idempotent — won't duplicate lines."""
    gitignore = tracking_path / ".gitignore"
    existing = gitignore.read_text() if gitignore.exists() else ""
    existing_lines = set(existing.splitlines())
    missing = [e for e in _GITIGNORE_ENTRIES if e not in existing_lines]
    if missing:
        separator = "\n" if existing and not existing.endswith("\n") else ""
        gitignore.write_text(existing + separator + "\n".join(missing) + "\n")


def write_json_exports(cfg: ProjConfig, project_name: str, *, force: bool = False) -> None:
    """Write derived JSON snapshots of todos/archive/decisions into the tracking dir.

    These files exist for git-diff readability only. SQL is the source of truth.
    No-op when git_tracking.enabled is False unless force=True.
    """
    if not force and not cfg.git_tracking.enabled:
        return

    from pathlib import Path as _Path

    from server.lib import sql_decisions, sql_todos

    proj_dir = _Path(cfg.tracking_dir).expanduser() / project_name
    _write_json(proj_dir / "todos.json", sql_todos.load_todos(cfg, project_name))
    _write_json(proj_dir / "archive.json", sql_todos.load_archived_todos(cfg, project_name))
    _write_json(proj_dir / "decisions.json", sql_decisions.load_decisions(cfg, project_name))


def _write_json(path: Path, items: list[Any]) -> None:
    """Atomically write a sorted JSON snapshot via a tmp file + rename."""

    payload = [dataclasses.asdict(t) for t in items]
    payload.sort(key=lambda d: d.get("id") or "")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _existing_flush_files(tracking_path: Path) -> list[str]:
    """Return subset of _FLUSH_FILES that exist on disk (avoids fatal git add errors)."""
    return [f for f in _FLUSH_FILES if (tracking_path / f).exists()]


def tracking_commit(tracking_path: Path, message: str) -> str | None:
    """Stage explicit allowed paths and commit. Returns commit SHA or None if nothing to commit."""
    existing = _existing_flush_files(tracking_path)
    if existing:
        _run(["git", "add", *existing], tracking_path)
    # Check if there are staged changes
    rc, _, _ = _run(["git", "diff", "--cached", "--quiet"], tracking_path)
    if rc == 0:
        # No changes staged
        return None
    rc, _stdout, _ = _run(["git", "commit", "-m", message], tracking_path)
    if rc != 0:
        return None
    # Get the commit SHA
    rc, sha, _ = _run(["git", "rev-parse", "--short", "HEAD"], tracking_path)
    return sha.strip() if rc == 0 else None


def resolve_repo_name(github_repo_format: str, project_name: str) -> str:
    """Apply the format template to produce a GitHub repo name."""
    return github_repo_format.replace("{project-name}", project_name)


def _get_github_user() -> str | None:
    """Get the authenticated GitHub username via gh CLI."""
    rc, stdout, _ = _run(["gh", "api", "user", "--jq", ".login"], ".")
    return stdout.strip() if rc == 0 and stdout.strip() else None


def ensure_github_repo(repo_name: str) -> bool:
    """Create a private GitHub repo if it doesn't exist. Returns True on success."""
    # Check if repo exists
    rc, _, _ = _run(["gh", "repo", "view", repo_name], ".")
    if rc == 0:
        return True  # Already exists
    # Create it
    rc, _, _ = _run(["gh", "repo", "create", repo_name, "--private", "--confirm"], ".")
    return rc == 0


def ensure_remote(tracking_path: Path, repo_name: str) -> bool:
    """Add 'origin' remote if not already configured. Returns True if remote exists."""
    rc, _, _ = _run(["git", "remote", "get-url", "origin"], tracking_path)
    if rc == 0:
        return True  # Remote already set
    user = _get_github_user()
    if not user:
        return False
    # Use the user/repo format if repo_name doesn't contain a slash
    remote_name = repo_name if "/" in repo_name else f"{user}/{repo_name}"
    rc, _, _ = _run(
        ["git", "remote", "add", "origin", f"https://github.com/{remote_name}.git"],
        tracking_path,
    )
    return rc == 0


def tracking_push(tracking_path: Path) -> bool:
    """Push to origin. On rejection, attempt pull --rebase and retry once."""
    rc, _, _ = _run(["git", "push", "-u", "origin", "HEAD"], tracking_path)
    if rc == 0:
        return True
    # Try pull --rebase then push again
    rc, _, _ = _run(["git", "pull", "--rebase", "origin", "HEAD"], tracking_path)
    if rc != 0:
        return False
    rc, _, _ = _run(["git", "push", "-u", "origin", "HEAD"], tracking_path)
    return rc == 0


# ---------------------------------------------------------------------------
# Async variants — offload blocking subprocess calls via asyncio.to_thread
# ---------------------------------------------------------------------------


async def _arun(cmd: list[str], cwd: str | Path) -> tuple[int, str, str]:
    """Async wrapper around _run(). Offloads to a thread to avoid blocking the event loop."""
    return await asyncio.to_thread(_run, cmd, cwd)


async def tracking_commit_async(tracking_path: Path, message: str) -> str | None:
    """Async variant of tracking_commit(). Stage explicit allowed paths and commit.

    Returns commit SHA or None if nothing to commit.
    """
    existing = _existing_flush_files(tracking_path)
    if existing:
        await _arun(["git", "add", *existing], tracking_path)
    rc, _, _ = await _arun(["git", "diff", "--cached", "--quiet"], tracking_path)
    if rc == 0:
        return None
    rc, _stdout, _ = await _arun(["git", "commit", "-m", message], tracking_path)
    if rc != 0:
        return None
    rc, sha, _ = await _arun(["git", "rev-parse", "--short", "HEAD"], tracking_path)
    return sha.strip() if rc == 0 else None


async def tracking_push_async(tracking_path: Path) -> bool:
    """Async variant of tracking_push(). Push to origin with pull-rebase retry."""
    rc, _, _ = await _arun(["git", "push", "-u", "origin", "HEAD"], tracking_path)
    if rc == 0:
        return True
    rc, _, _ = await _arun(["git", "pull", "--rebase", "origin", "HEAD"], tracking_path)
    if rc != 0:
        return False
    rc, _, _ = await _arun(["git", "push", "-u", "origin", "HEAD"], tracking_path)
    return rc == 0
