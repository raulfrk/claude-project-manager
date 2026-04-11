"""Branch-aware sync for the global CLAUDE.md managed section.

This script is invoked from the installer wizard's sync step. It detects
the current git branch via ``git symbolic-ref --short HEAD`` (not
``rev-parse``, so detached HEAD fails cleanly instead of returning
``HEAD``), and rewrites the managed section of ``~/.claude/CLAUDE.md`` to
match:

- on a ``*caveman*`` branch in ``claude-project-manager``: the default
  rules PLUS the caveman-mode append. A sidecar backup is created (or
  validated if already present) at ``~/.claude/CLAUDE.md.pre-caveman``
  with a magic header.
- on ``dev``, ``main``, or any other branch: the default rules. If a
  sidecar exists, its header is validated and restore runs, preserving
  non-managed user edits.
- on failure to detect branch (detached HEAD, git missing, subprocess
  timeout): no-op. The current managed section is preserved as-is.

This script is NOT invoked from SessionStart — branch checkout should
not silently mutate the user's home directory. The installer wizard run
is the opt-in moment (D519.3 decision).
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from installer.claudemd import (
    _backup_global_claudemd_for_caveman,
    _is_caveman_context,
    _restore_global_claudemd_from_caveman,
    ensure_managed_section,
)

if TYPE_CHECKING:
    from pathlib import Path

SyncStatus = Literal["caveman", "default", "noop"]


@dataclass(frozen=True)
class SyncResult:
    """Outcome of a branch-aware sync.

    ``status`` is one of:
    - ``"caveman"``: caveman variant installed, sidecar present
    - ``"default"``: default variant installed, sidecar restored if any
    - ``"noop"``: branch could not be detected; managed section untouched
    """

    status: SyncStatus
    branch: str | None
    modified: bool
    detail: str


def _detect_branch(repo_root: Path) -> str | None:
    """Return the current branch name, or None on any failure.

    Uses ``git symbolic-ref --short HEAD`` so a detached HEAD produces a
    non-zero exit (not the literal ``HEAD`` that ``rev-parse`` returns).
    """
    try:
        proc = subprocess.run(
            ["git", "symbolic-ref", "--short", "HEAD"],
            cwd=str(repo_root),
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        return None
    branch = proc.stdout.decode("utf-8", errors="replace").strip()
    return branch or None


def sync_claude_md(
    claude_md_path: Path,
    project_name: str,
    repo_root: Path,
) -> SyncResult:
    """Run the branch-aware sync for ``claude_md_path`` in ``project_name``.

    Parameters
    ----------
    claude_md_path:
        Path to the global CLAUDE.md file to sync (e.g.
        ``Path.home() / ".claude" / "CLAUDE.md"``).
    project_name:
        Name of the active project. Only ``claude-project-manager``
        participates in the caveman experiment; other projects get the
        default managed section regardless of branch.
    repo_root:
        Directory to run ``git symbolic-ref`` from. Typically the
        installer's detected repo root (i.e. the cpm worktree root).

    Returns
    -------
    SyncResult
    """
    branch = _detect_branch(repo_root)
    if branch is None:
        return SyncResult(
            status="noop",
            branch=None,
            modified=False,
            detail="git symbolic-ref failed (detached HEAD or git unavailable)",
        )

    if _is_caveman_context(project_name, branch):
        # Caveman branch: ensure sidecar exists (idempotent — first run
        # captures the pre-caveman state, subsequent runs leave it alone)
        # and install the caveman variant.
        sidecar_error = None
        if claude_md_path.exists():
            try:
                _backup_global_claudemd_for_caveman(claude_md_path)
            except (ValueError, FileNotFoundError) as exc:
                sidecar_error = str(exc)
        modified = ensure_managed_section(
            claude_md_path,
            project_name=project_name,
            current_branch=branch,
        )
        detail = f"caveman variant installed on branch {branch!r}"
        if sidecar_error is not None:
            detail += f"; sidecar error: {sidecar_error}"
        return SyncResult(
            status="caveman",
            branch=branch,
            modified=modified,
            detail=detail,
        )

    # Non-caveman branch. If a sidecar exists, run the restore path so
    # the managed section goes back to default while preserving user
    # edits. If no sidecar, a plain ensure_managed_section is enough.
    sidecar = claude_md_path.with_name(claude_md_path.name + ".pre-caveman")
    if sidecar.exists():
        try:
            modified = _restore_global_claudemd_from_caveman(claude_md_path)
        except (ValueError, FileNotFoundError) as exc:
            return SyncResult(
                status="noop",
                branch=branch,
                modified=False,
                detail=f"sidecar validation failed: {exc}",
            )
        return SyncResult(
            status="default",
            branch=branch,
            modified=modified,
            detail=f"restored default variant from sidecar on branch {branch!r}",
        )

    modified = ensure_managed_section(
        claude_md_path,
        project_name=project_name,
        current_branch=branch,
    )
    return SyncResult(
        status="default",
        branch=branch,
        modified=modified,
        detail=f"default variant ensured on branch {branch!r}",
    )
