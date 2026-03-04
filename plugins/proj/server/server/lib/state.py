"""Session-scoped in-memory state for the proj MCP server.

Each Claude session is a separate MCP server process, so module-level
variables here are naturally session-isolated without any persistence.
"""

from __future__ import annotations

_session_active_project: str | None = None


def get_session_active() -> str | None:
    """Return the session-scoped active project override, or None."""
    return _session_active_project


def set_session_active(name: str) -> None:
    """Set the session-scoped active project override (never written to disk)."""
    global _session_active_project
    _session_active_project = name


def clear_session_active() -> None:
    """Clear the session-scoped active project override."""
    global _session_active_project
    _session_active_project = None


def resolve_project(project_name: str | None) -> str | None:
    """Resolve which project to operate on.

    Resolution order: explicit project_name → session-scoped active → None.
    Tools should return 'No active project.' when this returns None.
    """
    return project_name or _session_active_project
