"""Pre-ingest filter for session files passed to wiki ingest subagent.

Strips todo-tracked content (todo IDs, status framing, "## Todos Worked On"
section) so wiki entities never pick up in-flight project state. See spec
docs/superpowers/specs/2026-04-26-wiki-ingest-todo-filter-design.md.
"""

from __future__ import annotations

import re

# Section heading + everything until next H2 or EOF.
_TODOS_WORKED_ON_RE = re.compile(r"(?ms)^[ \t]*## Todos Worked On\b.*?(?=^[ \t]*## |\Z)")

# Whole-line strip: explicit "todo NNN" / "todo-NNN" references.
_TODO_ID_EXPLICIT_RE = re.compile(r"(?im)^.*\btodo[\s-]*\d+\b.*$\n?")

# Whole-line strip: bare 3-4 digit id near an action/state verb (either order).
_BARE_VERBS = (
    r"(?:complete|completed|ship|shipped|close|closed|done|in-flight|active|ready|blocked)"
)
_TODO_ID_BARE_RE = re.compile(
    rf"(?im)^(?:.*\b\d{{3,4}}\b.*\b{_BARE_VERBS}\b|.*\b{_BARE_VERBS}\b.*\b\d{{3,4}}\b).*$\n?"
)

# Whole-line strip: status-framing phrases.
_STATUS_PHRASES = (
    r"(?:in-flight|active improvement axis|active improvement|shipped this session"
    r"|ready to start|blocked on|in progress|currently working)"
)
_STATUS_PHRASE_RE = re.compile(rf"(?im)^.*\b{_STATUS_PHRASES}\b.*$\n?")


def filter_session_text(text: str) -> str:
    """Apply 3 strip passes in order: section, todo-id, status-phrase.

    Returns the filtered text. Whole-line strip is used (not match-only) so
    paragraph readability is preserved for what remains.
    """
    out = _TODOS_WORKED_ON_RE.sub("", text)
    out = _TODO_ID_EXPLICIT_RE.sub("", out)
    out = _TODO_ID_BARE_RE.sub("", out)
    out = _STATUS_PHRASE_RE.sub("", out)
    return out
