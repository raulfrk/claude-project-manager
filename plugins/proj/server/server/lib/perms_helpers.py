"""Shared helpers for perms_grant and perms_sync tools."""

from __future__ import annotations

import json
from pathlib import Path

from server.lib.models import ProjectMeta

_USER_SETTINGS = Path.home() / ".claude" / "settings.json"
_USER_LOCAL_SETTINGS = Path.home() / ".claude" / "settings.local.json"
_WORKTREE_CONFIG = Path.home() / ".claude" / "worktree.yaml"


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


def _sandbox_paths(project_dir: Path | None = None, project_dirs: list[Path] | None = None) -> list[Path]:
    """Return settings.local.json paths to check for sandbox mode."""
    paths = [_USER_LOCAL_SETTINGS]
    if project_dirs:
        for d in project_dirs:
            paths.append(Path(d) / ".claude" / "settings.local.json")
    elif project_dir:
        paths.append(Path(project_dir) / ".claude" / "settings.local.json")
    return paths


def is_sandbox_enabled(project_dir: Path | None = None, project_dirs: list[Path] | None = None) -> bool:
    """Check if sandbox mode is enabled in user-level or project-level settings.local.json."""
    for path in _sandbox_paths(project_dir, project_dirs):
        if not path.exists():
            continue
        try:
            data: dict[str, object] = json.loads(path.read_text())
            sandbox = data.get("sandbox", {})
            if isinstance(sandbox, dict) and sandbox.get("enabled", False):
                return True
        except Exception:  # noqa: BLE001
            pass
    return False


def effective_settings_path(project_dir: Path | None = None) -> Path:
    """Return settings.json or settings.local.json depending on sandbox mode."""
    if is_sandbox_enabled(project_dir):
        return _USER_LOCAL_SETTINGS
    return _USER_SETTINGS
