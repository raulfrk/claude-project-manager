#!/usr/bin/env python3
"""Tally postmortems in a tracking-dir NOTES.md by class line."""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "_shared"))
from postmortem.parse import iter_postmortems  # noqa: E402


def tally(notes_md: Path) -> Counter[str]:
    classes: Counter[str] = Counter()
    for entry in iter_postmortems(notes_md):
        classes[entry.cls or "<unparsed>"] += 1
    return classes


def main() -> int:
    notes = Path(sys.argv[1] if len(sys.argv) > 1 else "NOTES.md")
    if not notes.is_file():
        print(f"error: {notes} not found", file=sys.stderr)
        return 1
    for cls, count in tally(notes).most_common():
        print(f"{count:4d}\t{cls}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
