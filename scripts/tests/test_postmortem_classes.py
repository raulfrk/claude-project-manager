"""Unit tests for scripts/postmortem_classes.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    pass

import postmortem_classes


def test_tally_empty_notes(tmp_path: Path) -> None:
    notes = tmp_path / "NOTES.md"
    notes.write_text("")
    result = postmortem_classes.tally(notes)
    assert result == {}


def test_tally_single_class(tmp_path: Path) -> None:
    notes = tmp_path / "NOTES.md"
    notes.write_text("## [2026-04-27 12:00] postmortem | 799\nclass: boundary-drift\n")
    result = postmortem_classes.tally(notes)
    assert dict(result) == {"boundary-drift": 1}


def test_tally_multiple_sorted_by_count(tmp_path: Path) -> None:
    notes = tmp_path / "NOTES.md"
    notes.write_text(
        "## [2026-04-27 12:00] postmortem | a\nclass: boundary-drift\n\n"
        "## [2026-04-27 13:00] postmortem | b\nclass: boundary-drift\n\n"
        "## [2026-04-27 14:00] postmortem | c\nclass: mast:verification:no-verification\n\n"
        "## [2026-04-27 15:00] postmortem | d\nclass: boundary-drift\n"
    )
    result = postmortem_classes.tally(notes)
    ordered = result.most_common()
    assert ordered[0] == ("boundary-drift", 3)
    assert ordered[1] == ("mast:verification:no-verification", 1)


def test_tally_unparsed_aggregated(tmp_path: Path) -> None:
    notes = tmp_path / "NOTES.md"
    notes.write_text(
        "## [2026-04-27 12:00] postmortem | a\nno class line here\n\n"
        "## [2026-04-27 13:00] postmortem | b\nstill nothing\n"
    )
    result = postmortem_classes.tally(notes)
    assert result == {"<unparsed>": 2}


def test_main_missing_file_returns_1(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / "no_such_file.md"
    sys.argv = ["postmortem_classes.py", str(missing)]
    rc = postmortem_classes.main()
    assert rc == 1
    captured = capsys.readouterr()
    assert "not found" in captured.err


def test_cli_output_format(tmp_path: Path) -> None:
    """Subprocess invocation: stdout format `<count>\\t<class>` per line."""
    notes = tmp_path / "NOTES.md"
    notes.write_text(
        "## [2026-04-27 12:00] postmortem | a\nclass: boundary-drift\n\n"
        "## [2026-04-27 13:00] postmortem | b\nclass: boundary-drift\n\n"
        "## [2026-04-27 14:00] postmortem | c\nclass: microsoft:rogue-actions\n"
    )
    script = Path(__file__).resolve().parent.parent / "postmortem_classes.py"
    result = subprocess.run(
        [sys.executable, str(script), str(notes)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.strip().splitlines()
    assert len(lines) == 2
    # Highest count first
    assert lines[0].split("\t")[1] == "boundary-drift"
    assert lines[0].split("\t")[0].strip() == "2"
    assert lines[1].split("\t")[1] == "microsoft:rogue-actions"
