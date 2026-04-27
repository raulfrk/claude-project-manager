"""Unit tests for plugins/_shared/postmortem/parse.py."""

from __future__ import annotations

import os
import time
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from postmortem.parse import (
    LOOKAHEAD_BYTES,
    POSTMORTEM_HEADING_RE,
    Postmortem,
    has_recent_postmortem,
    iter_postmortems,
)


def test_empty_file_yields_zero_entries(tmp_path: Path) -> None:
    notes = tmp_path / "NOTES.md"
    notes.write_text("")
    assert list(iter_postmortems(notes)) == []


def test_single_postmortem_with_class_line(tmp_path: Path) -> None:
    notes = tmp_path / "NOTES.md"
    notes.write_text(
        "## [2026-04-27 12:00] postmortem | 799\n"
        "1. what: thing broke\n"
        "2. why: race condition\n"
        "3. class: mast:verification:incorrect-verification\n"
        "4. prevented: tests\n"
        "5. detected: monitoring\n"
    )
    entries = list(iter_postmortems(notes))
    assert len(entries) == 1
    assert entries[0].timestamp == "2026-04-27 12:00"
    assert entries[0].bug_id == "799"
    assert entries[0].cls == "mast:verification:incorrect-verification"


def test_mast_format_preserved_verbatim(tmp_path: Path) -> None:
    notes = tmp_path / "NOTES.md"
    notes.write_text(
        "## [2026-04-27 12:00] postmortem | bug-1\nClass: mast:spec/design:role-violation\n"
    )
    [entry] = list(iter_postmortems(notes))
    assert entry.cls == "mast:spec/design:role-violation"


def test_microsoft_format_preserved_verbatim(tmp_path: Path) -> None:
    notes = tmp_path / "NOTES.md"
    notes.write_text(
        "## [2026-04-27 12:00] postmortem | abc123\n3. class: microsoft:silent-degradation\n"
    )
    [entry] = list(iter_postmortems(notes))
    assert entry.cls == "microsoft:silent-degradation"


def test_no_class_line_returns_none(tmp_path: Path) -> None:
    notes = tmp_path / "NOTES.md"
    notes.write_text("## [2026-04-27 12:00] postmortem | 800\nwhat: stuff\nwhy: reasons\n")
    [entry] = list(iter_postmortems(notes))
    assert entry.cls is None


def test_multiple_postmortems_all_yielded(tmp_path: Path) -> None:
    notes = tmp_path / "NOTES.md"
    notes.write_text(
        "## [2026-04-27 12:00] postmortem | 799\n"
        "class: boundary-drift\n\n"
        "## [2026-04-27 13:00] postmortem | 800\n"
        "class: mast:verification:no-verification\n\n"
        "## [2026-04-27 14:00] postmortem | 801\n"
        "class: microsoft:context-blindness\n"
    )
    entries = list(iter_postmortems(notes))
    assert [e.bug_id for e in entries] == ["799", "800", "801"]
    assert [e.cls for e in entries] == [
        "boundary-drift",
        "mast:verification:no-verification",
        "microsoft:context-blindness",
    ]


def test_class_line_beyond_lookahead_returns_none(tmp_path: Path) -> None:
    notes = tmp_path / "NOTES.md"
    padding = "x" * (LOOKAHEAD_BYTES + 200)
    notes.write_text(
        "## [2026-04-27 12:00] postmortem | far\n" + padding + "\nclass: boundary-drift\n"
    )
    [entry] = list(iter_postmortems(notes))
    assert entry.cls is None


def test_non_postmortem_headings_skipped(tmp_path: Path) -> None:
    notes = tmp_path / "NOTES.md"
    notes.write_text(
        "## [2026-04-27 11:00] note | unrelated\n"
        "class: should-not-match\n\n"
        "## [2026-04-27 12:00] decision | something\n"
        "class: also-skipped\n\n"
        "## [2026-04-27 13:00] postmortem | real\n"
        "class: boundary-drift\n"
    )
    entries = list(iter_postmortems(notes))
    assert len(entries) == 1
    assert entries[0].bug_id == "real"
    assert entries[0].cls == "boundary-drift"


def test_heading_re_strict_no_false_positive_on_note(tmp_path: Path) -> None:
    """Regex must not match 'note |' or other ops as 'postmortem |'."""
    notes_text = "## [2026-04-27 11:00] note | sample\n## [2026-04-27 12:00] postmortemish | nope\n"
    assert POSTMORTEM_HEADING_RE.search(notes_text) is None


def test_postmortem_dataclass_is_frozen() -> None:
    pm = Postmortem(timestamp="2026-04-27 12:00", bug_id="799", cls="boundary-drift")
    with pytest.raises(FrozenInstanceError):
        pm.cls = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# has_recent_postmortem
# ---------------------------------------------------------------------------


def test_has_recent_postmortem_missing_dir(tmp_path: Path) -> None:
    assert has_recent_postmortem(tmp_path / "missing", 24) is False


def test_has_recent_postmortem_finds_within_window(tmp_path: Path) -> None:
    proj = tmp_path / "proj1"
    proj.mkdir()
    notes = proj / "NOTES.md"
    notes.write_text("## [2026-04-27 12:00] postmortem | 799\nclass: boundary-drift\n")
    assert has_recent_postmortem(tmp_path, 24) is True


def test_has_recent_postmortem_skips_old_files(tmp_path: Path) -> None:
    proj = tmp_path / "proj1"
    proj.mkdir()
    notes = proj / "NOTES.md"
    notes.write_text("## [2025-01-01 00:00] postmortem | ancient\n")
    # Backdate mtime by 30 days
    old = time.time() - 30 * 86400
    os.utime(notes, (old, old))
    assert has_recent_postmortem(tmp_path, 24) is False


def test_has_recent_postmortem_no_postmortem_in_recent_file(tmp_path: Path) -> None:
    proj = tmp_path / "proj1"
    proj.mkdir()
    notes = proj / "NOTES.md"
    notes.write_text("## [2026-04-27 12:00] note | nothing-here\n")
    assert has_recent_postmortem(tmp_path, 24) is False
