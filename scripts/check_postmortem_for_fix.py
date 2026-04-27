#!/usr/bin/env python3
"""Soft-warn pre-commit hook: fix/bug commit without recent postmortem.

Resolution order for tracking dir:
1. ``CPM_TRACKING_DIR`` env var (explicit override)
2. ``tracking_dir`` from ``~/.claude/proj.yaml``
3. ``~/projects/tracking`` (legacy default)

Always exits 0 (soft-warn). To strict-block in future, swap to exit 1.
"""

from __future__ import annotations

import os
import re
import sys
import time
from pathlib import Path

# Reuse shared parser
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins" / "_shared"))
from postmortem.parse import POSTMORTEM_HEADING_RE  # noqa: E402

FIX_PREFIX_RE = re.compile(r"^(fix|bug)\(")
RECENT_HOURS = 24


def _resolve_tracking_dir() -> Path:
    env = os.environ.get("CPM_TRACKING_DIR")
    if env:
        return Path(env).expanduser()
    proj_yaml = Path.home() / ".claude" / "proj.yaml"
    if proj_yaml.is_file():
        try:
            for line in proj_yaml.read_text(errors="replace").splitlines():
                if line.startswith("tracking_dir:"):
                    val = line.split(":", 1)[1].strip().strip('"').strip("'")
                    if val:
                        return Path(val).expanduser()
        except OSError:
            pass
    return Path.home() / "projects" / "tracking"


def _has_recent_postmortem(tracking_dir: Path, within_hours: int) -> bool:
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


def main() -> int:
    msg_file = Path(sys.argv[1] if len(sys.argv) > 1 else ".git/COMMIT_EDITMSG")
    if not msg_file.is_file():
        return 0
    lines = msg_file.read_text(errors="replace").splitlines()
    if not lines or not FIX_PREFIX_RE.match(lines[0]):
        return 0  # not a fix/bug commit
    tracking_dir = _resolve_tracking_dir()
    if _has_recent_postmortem(tracking_dir, RECENT_HOURS):
        return 0
    print(
        f"\nWARN: fix commit without recent postmortem in {tracking_dir}/*/NOTES.md\n"
        "    Per managed CLAUDE.md rule 'Postmortem ritual' write 5-line\n"
        "    postmortem BEFORE fixing. Use notes_append w/ heading:\n"
        "      ## [YYYY-MM-DD HH:MM] postmortem | <id>\n"
        "    (Soft-warn for now; will block in future. See todo 799.)\n",
        file=sys.stderr,
    )
    return 0  # soft-warn: always exit 0


if __name__ == "__main__":
    sys.exit(main())
