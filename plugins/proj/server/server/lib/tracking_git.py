"""Git tracking for project tracking directories — auto-commit and optional GitHub push."""

from __future__ import annotations

import subprocess
from pathlib import Path


def resolve_config(
    cfg: object, meta: object,
) -> tuple[bool, bool, str]:
    """Resolve effective (enabled, github_enabled, github_repo_format) from global + per-project.

    Per-project values of None fall through to global defaults.
    """
    from server.lib.models import ProjConfig, ProjectMeta

    assert isinstance(cfg, ProjConfig)
    assert isinstance(meta, ProjectMeta)
    enabled = meta.git_tracking.enabled if meta.git_tracking.enabled is not None else cfg.git_tracking.enabled
    github = meta.git_tracking.github_enabled if meta.git_tracking.github_enabled is not None else cfg.git_tracking.github_enabled
    fmt = meta.git_tracking.github_repo_format if meta.git_tracking.github_repo_format is not None else cfg.git_tracking.github_repo_format
    return enabled, github, fmt


def _run(cmd: list[str], cwd: str | Path) -> tuple[int, str, str]:
    """Run a command and return (returncode, stdout, stderr).
    Returns (1, '', 'command not found') if the executable is missing.
    """
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, cwd=str(cwd), check=False,
        )
        return result.returncode, result.stdout, result.stderr
    except (FileNotFoundError, subprocess.SubprocessError):
        return 1, "", "command not found"


def is_git_repo(tracking_path: Path) -> bool:
    """Check if tracking_path is inside a git repo."""
    rc, _, _ = _run(["git", "rev-parse", "--git-dir"], tracking_path)
    return rc == 0


def ensure_git_repo(tracking_path: Path) -> bool:
    """Initialize a git repo if not already one. Creates .gitignore. Returns True on success."""
    tracking_path.mkdir(parents=True, exist_ok=True)
    if is_git_repo(tracking_path):
        return True
    rc, _, _ = _run(["git", "init"], tracking_path)
    if rc != 0:
        return False
    # Create .gitignore for temp files from atomic writes
    gitignore = tracking_path / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("*.tmp\n__pycache__/\n*.pyc\n")
    return True


def tracking_commit(tracking_path: Path, message: str) -> str | None:
    """Stage all changes and commit. Returns commit SHA or None if nothing to commit."""
    _run(["git", "add", "-A"], tracking_path)
    # Check if there are staged changes
    rc, _, _ = _run(["git", "diff", "--cached", "--quiet"], tracking_path)
    if rc == 0:
        # No changes staged
        return None
    rc, stdout, _ = _run(["git", "commit", "-m", message], tracking_path)
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
