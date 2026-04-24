"""Session-scoped state for proj MCP server.

Active project is session-scoped AND file-backed for cross-process visibility
(wiki plugin reads proj-session.yaml via wiki_scope_detect). In-memory state
takes priority per process; the on-disk file is pid-keyed so multiple concurrent
Claude Code sessions do not clobber each other. All file I/O is delegated to
the shared `session_key` helper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import session_key

_SESSION_FILE: Final[Path] = Path.home() / ".claude" / "proj-session.yaml"

# Wrapped so tests can monkey-patch without touching psutil internals.
_session_key_fn = session_key.get_claude_session_key

_session_active_project: str | None = None


def get_session_active() -> str | None:
    """Return the session-scoped active project.

    In-memory state wins; falls back to the pid-keyed on-disk session file
    (useful after MCP server restarts within the same Claude Code session).
    """
    if _session_active_project is not None:
        return _session_active_project
    return session_key.read_active(_SESSION_FILE, session_key=_session_key_fn())


def set_session_active(name: str) -> None:
    """Set the session-scoped active project. Writes to both in-memory + disk."""
    global _session_active_project
    _session_active_project = name
    session_key.write_active(_SESSION_FILE, name, session_key=_session_key_fn())


def clear_session_active() -> None:
    """Clear session-scoped active project from both in-memory + disk. Idempotent."""
    global _session_active_project
    _session_active_project = None
    session_key.clear_active(_SESSION_FILE, session_key=_session_key_fn())


def resolve_project(project_name: str | None) -> str | None:
    """Resolve which project to operate on.

    Resolution order: explicit project_name → session-scoped active → None.
    Tools should return 'No active project.' when this returns None.
    """
    return project_name or get_session_active()
