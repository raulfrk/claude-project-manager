"""Shared parser for postmortem entries in tracking-dir NOTES.md."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

POSTMORTEM_HEADING_RE = re.compile(
    r"^## \[(?P<ts>[\d-]+ [\d:]+)\] postmortem \| (?P<id>.+)$",
    re.MULTILINE,
)
CLASS_LINE_RE = re.compile(
    r"^(?:\d+\.\s*)?(?:class|Class)[:\s]+(?P<cls>\S.*)$",
    re.MULTILINE,
)
LOOKAHEAD_BYTES = 1024


@dataclass(frozen=True)
class Postmortem:
    timestamp: str
    bug_id: str
    cls: str | None


def iter_postmortems(notes_md: Path) -> Iterator[Postmortem]:
    """Yield Postmortem entries parsed from notes_md, in file order."""
    text = notes_md.read_text(errors="replace")
    for match in POSTMORTEM_HEADING_RE.finditer(text):
        section = text[match.end() : match.end() + LOOKAHEAD_BYTES]
        cls_match = CLASS_LINE_RE.search(section)
        cls = cls_match.group("cls").strip() if cls_match else None
        yield Postmortem(
            timestamp=match.group("ts"),
            bug_id=match.group("id"),
            cls=cls,
        )


def has_recent_postmortem(tracking_dir: Path, within_hours: int) -> bool:
    """Return True iff some NOTES.md under tracking_dir has a postmortem heading
    AND its mtime is within the past ``within_hours``."""
    if not tracking_dir.is_dir():
        return False
    cutoff = time.time() - within_hours * 3600
    for notes in tracking_dir.rglob("NOTES.md"):
        try:
            if notes.stat().st_mtime < cutoff:
                continue
            if POSTMORTEM_HEADING_RE.search(notes.read_text(errors="replace")):
                return True
        except OSError:
            continue
    return False
