"""Session-scoped state for proj MCP server.

Active project is session-scoped but now file-backed for cross-process visibility
(wiki plugin reads proj-session.yaml via wiki_scope_detect). In-memory state
takes priority; file provides fallback/persistence across MCP server restarts.
"""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Final

import yaml

_SESSION_FILE: Final[Path] = Path.home() / ".claude" / "proj-session.yaml"

_session_active_project: str | None = None


def _atomic_write(target: Path, content: str) -> None:
    """Atomically write content to target via tmpfile + rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        Path(tmp).replace(target)
    except Exception:
        with suppress(FileNotFoundError):
            Path(tmp).unlink()
        raise


def _read_session_file() -> str | None:
    """Read active-project name from session file. Returns None if missing/malformed."""
    if not _SESSION_FILE.exists():
        return None
    try:
        with _SESSION_FILE.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("active")
    return str(value) if value else None


def get_session_active() -> str | None:
    """Return the session-scoped active project.

    In-memory state wins; falls back to on-disk session file (useful after MCP
    server restarts).
    """
    if _session_active_project is not None:
        return _session_active_project
    return _read_session_file()


def set_session_active(name: str) -> None:
    """Set the session-scoped active project. Writes to both in-memory + disk."""
    global _session_active_project
    _session_active_project = name
    _atomic_write(_SESSION_FILE, yaml.safe_dump({"active": name}, sort_keys=False))


def clear_session_active() -> None:
    """Clear session-scoped active project from both in-memory + disk. Idempotent."""
    global _session_active_project
    _session_active_project = None
    if _SESSION_FILE.exists():
        _SESSION_FILE.unlink()


def resolve_project(project_name: str | None) -> str | None:
    """Resolve which project to operate on.

    Resolution order: explicit project_name → session-scoped active → None.
    Tools should return 'No active project.' when this returns None.
    """
    return project_name or get_session_active()
