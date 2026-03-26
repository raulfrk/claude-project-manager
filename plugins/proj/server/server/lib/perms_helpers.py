"""Shared helpers for perms_grant and perms_sync tools."""

from __future__ import annotations

from pathlib import Path

from server.lib.models import ProjectMeta

_USER_SETTINGS = Path.home() / ".claude" / "settings.json"
_USER_LOCAL_SETTINGS = Path.home() / ".claude" / "settings.local.json"


def project_dirs_from_meta(meta: ProjectMeta) -> list[Path]:
    """Return all non-reference repo paths (or first repo if all are reference)."""
    dirs = [Path(repo.path) for repo in meta.repos if not repo.reference]
    if not dirs and meta.repos:
        dirs = [Path(meta.repos[0].path)]
    return dirs


def project_dir_from_meta(meta: ProjectMeta) -> Path | None:
    """Derive the project directory from the first non-reference repo path."""
    dirs = project_dirs_from_meta(meta)
    return dirs[0] if dirs else None
