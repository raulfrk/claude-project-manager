"""Local marketplace clone management for the installer.

Clones the claude-project-manager marketplace repo into a fixed cache
directory so the installer can register a local path as the Claude Code
marketplace source (used by --local-marketplace).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from installer.errors import InstallerError

if TYPE_CHECKING:
    from rich.console import Console


def _status(console: Console | None, msg: str) -> None:
    """Emit a status line either via Rich console or stderr fallback."""
    if console is not None:
        console.print(msg)
    else:
        # Strip Rich markup tags for the plain-text fallback
        import re

        plain = re.sub(r"\[/?[^\]]+\]", "", msg)
        print(plain, file=sys.stderr)


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


def ensure_local_clone(
    branch: str | None = None, console: Console | None = None
) -> Path:
    """Ensure a fresh clone at ``LOCAL_CLONE_DIR`` on the given branch.

    Behavior:
    - ``git`` missing on PATH → ``InstallerError``.
    - Dir exists: removed via ``shutil.rmtree`` before re-cloning. Always
      yields a clean checkout, no stale state from prior runs.
    - Clone steps: parent created, then ``git clone _HTTPS_SOURCE LOCAL_CLONE_DIR``,
      followed by ``git fetch origin``, ``git checkout <branch>``, and
      ``git reset --hard origin/<branch>``.

    When ``branch`` is ``None``, resolves the remote's default branch via
    ``_default_branch`` and uses that.

    When ``console`` is provided, emits Rich-styled status updates for
    each step. Without a console, falls back to plain stderr lines.

    Returns the absolute path to the clone.
    """
    if shutil.which("git") is None:
        raise InstallerError("git not found on PATH")

    dest = LOCAL_CLONE_DIR

    if dest.exists():
        _status(console, f"[yellow]Removing existing local clone at {dest}...[/yellow]")
        try:
            shutil.rmtree(dest)
        except OSError as exc:
            raise InstallerError(
                f"Failed to remove existing local clone at {dest}: {exc}. "
                f"Check permissions or remove manually with `rm -rf {dest}`."
            ) from exc
        if dest.exists():
            raise InstallerError(
                f"rmtree completed but {dest} still exists — partial filesystem state. "
                f"Remove manually with `rm -rf {dest}` and retry."
            )

    dest.parent.mkdir(parents=True, exist_ok=True)
    _status(console, f"[bold]Cloning {_HTTPS_SOURCE} → {dest}...[/bold]")
    _run_git(["clone", _HTTPS_SOURCE, str(dest)], cwd=None)

    target = branch or _default_branch(dest)
    _status(console, f"[bold]Fetching origin + checking out {target}...[/bold]")
    _run_git(["fetch", "origin"], cwd=dest)
    _run_git(["checkout", target], cwd=dest)
    _run_git(["reset", "--hard", f"origin/{target}"], cwd=dest)
    _status(console, f"  [green]✓[/green] Local clone ready at {dest} ({target})")
    return dest
