"""Shared postmortem parser: regex constants + dataclass + iter/has helpers.

Used by proj's `server.cli` (Claude Code hooks) AND `scripts/` (pre-commit
+ tallier). Single source of truth for the postmortem heading format.
"""

from postmortem.parse import (
    CLASS_LINE_RE,
    LOOKAHEAD_BYTES,
    POSTMORTEM_HEADING_RE,
    Postmortem,
    has_recent_postmortem,
    iter_postmortems,
)

__all__ = [
    "CLASS_LINE_RE",
    "LOOKAHEAD_BYTES",
    "POSTMORTEM_HEADING_RE",
    "Postmortem",
    "has_recent_postmortem",
    "iter_postmortems",
]
