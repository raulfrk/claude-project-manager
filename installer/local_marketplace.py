"""Local marketplace clone management for the installer.

Clones the claude-project-manager marketplace repo into a fixed cache
directory so the installer can register a local path as the Claude Code
marketplace source (used by --local-marketplace).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from installer.errors import InstallerError

LOCAL_CLONE_DIR = (
    Path.home() / ".cache" / "claude-project-manager" / "local-marketplace"
)
_HTTPS_SOURCE = "https://github.com/raulfrk/claude-project-manager.git"
_GIT_TIMEOUT = 120  # seconds


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
