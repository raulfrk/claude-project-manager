"""Session-scoped active-project state shared between proj and wiki plugins.

Exposes pid-keyed read/write/clear over ~/.claude/proj-session.yaml v2 schema
so concurrent Claude Code sessions don't clobber each other.
"""

from __future__ import annotations

from session_key.session_key import (
    clear_active,
    get_claude_session_key,
    read_active,
    write_active,
)

__all__ = [
    "clear_active",
    "get_claude_session_key",
    "read_active",
    "write_active",
]
