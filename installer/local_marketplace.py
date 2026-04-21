"""Local marketplace clone management for the installer.

Clones the claude-project-manager marketplace repo into a fixed cache
directory so the installer can register a local path as the Claude Code
marketplace source (used by --local-marketplace).
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from installer.errors import InstallerError

LOCAL_CLONE_DIR = (
    Path.home() / ".cache" / "claude-project-manager" / "local-marketplace"
)
_HTTPS_SOURCE = "https://github.com/raulfrk/claude-project-manager.git"
_GIT_TIMEOUT = 120  # seconds
_DEFAULT_BRANCH_FALLBACK = "main"


def _run_git(args: list[str], *, cwd: Path | None) -> subprocess.CompletedProcess[str]:
    """Run ``git <args>`` and return the result.

    Mirrors ``installer.plugin_cli._run``:
    - ``stdin=DEVNULL`` prevents the child from grabbing the controlling TTY.
    - Timeout fires ``InstallerError``.
    - Non-zero exit fires ``InstallerError`` with combined stderr/stdout.
    """
    cmd = ["git", *args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=_GIT_TIMEOUT,
            stdin=subprocess.DEVNULL,
            cwd=cwd,
        )
    except subprocess.TimeoutExpired as exc:
        raise InstallerError(
            f"git command timed out after {_GIT_TIMEOUT}s: {' '.join(cmd)}"
        ) from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise InstallerError(
            f"git failed (exit {result.returncode}): {' '.join(cmd)}\n{detail}"
        )
    return result


def _is_valid_clone(path: Path) -> bool:
    """Return True if *path* is an existing clone of ``_HTTPS_SOURCE``.

    Checks:
    - ``path`` exists and contains a ``.git`` entry
    - ``git -C <path> remote get-url origin`` returns ``_HTTPS_SOURCE``
    """
    if not (path / ".git").exists():
        return False
    try:
        result = _run_git(["remote", "get-url", "origin"], cwd=path)
    except InstallerError:
        return False
    return result.stdout.strip() == _HTTPS_SOURCE


def _default_branch(repo_dir: Path) -> str:
    """Return the repo's default branch by resolving ``origin/HEAD``.

    Falls back to ``main`` if ``origin/HEAD`` is not set (some clones skip
    ``--origin-head`` resolution).
    """
    try:
        result = _run_git(
            ["symbolic-ref", "refs/remotes/origin/HEAD"],
            cwd=repo_dir,
        )
    except InstallerError:
        return _DEFAULT_BRANCH_FALLBACK
    # Output: "refs/remotes/origin/<branch>" — may include nested slashes
    return result.stdout.strip().removeprefix("refs/remotes/origin/")


def ensure_local_clone(branch: str | None = None) -> Path:
    """Ensure a valid clone at ``LOCAL_CLONE_DIR`` on the given branch.

    Behavior:
    - ``git`` missing on PATH → ``InstallerError``.
    - Dir missing: parent created, then ``git clone _HTTPS_SOURCE LOCAL_CLONE_DIR``,
      followed by ``git checkout <branch>`` and ``git reset --hard origin/<branch>``
      when ``branch`` differs from the clone's initial HEAD.
    - Dir exists and is a valid clone: ``git fetch origin``, ``git checkout <branch>``,
      ``git reset --hard origin/<branch>``.
    - Dir exists but is not a valid clone (stray files or wrong remote):
      ``InstallerError`` with guidance to delete the path.

    When ``branch`` is ``None``, resolves the remote's default branch via
    ``_default_branch`` and uses that.

    Returns the absolute path to the clone.
    """
    if shutil.which("git") is None:
        raise InstallerError("git not found on PATH")

    dest = LOCAL_CLONE_DIR

    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        _run_git(["clone", _HTTPS_SOURCE, str(dest)], cwd=None)
        target = branch or _default_branch(dest)
        _run_git(["fetch", "origin"], cwd=dest)
        _run_git(["checkout", target], cwd=dest)
        _run_git(["reset", "--hard", f"origin/{target}"], cwd=dest)
        return dest

    if not _is_valid_clone(dest):
        raise InstallerError(
            f"Cache dir at {dest} is not a valid clone of {_HTTPS_SOURCE}. "
            f"Delete it and retry."
        )

    target = branch or _default_branch(dest)
    _run_git(["fetch", "origin"], cwd=dest)
    _run_git(["checkout", target], cwd=dest)
    _run_git(["reset", "--hard", f"origin/{target}"], cwd=dest)
    return dest
