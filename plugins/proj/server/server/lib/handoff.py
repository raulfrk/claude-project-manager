"""Parse `## Next Session Resumes Here` block from a session file.

Used by `/proj:load` to surface a coordinator-style handoff (Attempted /
Blocked / Next Action / Files / Todos) at the top of session ctx so a fresh
agent can resume without re-reading the whole session.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

HANDOFF_HEADING_RE = re.compile(r"^## Next Session Resumes Here\s*$", re.MULTILINE)
SUBSECTION_HEADING_RE = re.compile(
    r"^### (?P<name>Attempted|Blocked|Next Action|Files / Todos)\s*$",
    re.MULTILINE,
)
_PLACEHOLDERS = {
    "_(none)_",
    "_(none specified)_",
    "_(no concrete next action — review session or ask user)_",
}


@dataclass(frozen=True)
class HandoffBlock:
    """Parsed handoff block w/ 4 named subsections."""

    attempted: str
    blocked: str
    next_action: str
    files_todos: str

    def is_empty_placeholder(self, field: str) -> bool:
        """Return True iff the named field's body is one of the known placeholders.

        Strips a single leading bullet (``- ``) before comparison, since the
        save template emits placeholders as bullet items.
        """
        body = getattr(self, field).strip()
        body = re.sub(r"^-\s*", "", body)
        return body in _PLACEHOLDERS


def parse_handoff(session_md: Path) -> HandoffBlock | None:
    """Parse the first ``## Next Session Resumes Here`` block from ``session_md``.

    Returns ``None`` when the heading is absent (legacy session files).
    Returns a ``HandoffBlock`` w/ 4 subsections; missing subsections become
    empty strings.
    """
    text = session_md.read_text(errors="replace")
    handoff_match = HANDOFF_HEADING_RE.search(text)
    if not handoff_match:
        return None
    section = text[handoff_match.end() :]
    next_h2 = re.search(r"^## (?!#)", section, re.MULTILINE)
    if next_h2:
        section = section[: next_h2.start()]

    subs: dict[str, str] = {}
    matches = list(SUBSECTION_HEADING_RE.finditer(section))
    for i, match in enumerate(matches):
        name = match.group("name")
        body_start = match.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        subs[name] = section[body_start:body_end].strip()

    return HandoffBlock(
        attempted=subs.get("Attempted", ""),
        blocked=subs.get("Blocked", ""),
        next_action=subs.get("Next Action", ""),
        files_todos=subs.get("Files / Todos", ""),
    )
