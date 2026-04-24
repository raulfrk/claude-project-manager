"""pid-scoped read/write of ~/.claude/proj-session.yaml for multi-session safety."""

from __future__ import annotations

import os
import re
from typing import TYPE_CHECKING

import psutil

if TYPE_CHECKING:
    from pathlib import Path

_DEFAULT_MATCHER: re.Pattern[str] = re.compile(r"(?:^|/)claude(?:\s|$)")


def _get_matcher() -> re.Pattern[str]:
    """Return the cmdline matcher regex for Claude Code ancestor detection.

    Default matches an exec path ending in `claude` or a cmdline where the first
    token is `claude`. Override via env var CPM_CLAUDE_CODE_CMDLINE_MATCHER.
    """
    custom = os.getenv("CPM_CLAUDE_CODE_CMDLINE_MATCHER")
    if custom:
        return re.compile(custom)
    return _DEFAULT_MATCHER


def _cmdline_str(parts: list[str]) -> str:
    """Render cmdline list as a single space-joined string for regex matching."""
    return " ".join(parts)


def get_claude_session_key() -> str:
    """Return Claude Code ancestor pid (as str) for the current process.

    Walks the ppid chain via psutil, returning the first ancestor whose cmdline
    matches the matcher regex. Falls back to the current process pid if no
    Claude Code ancestor is found (single-process/test scenarios).
    """
    matcher = _get_matcher()
    try:
        self_proc = psutil.Process()
        for ancestor in self_proc.parents():
            if matcher.search(_cmdline_str(ancestor.cmdline())):
                return str(ancestor.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return str(os.getpid())


def read_active(file: Path, session_key: str | None = None) -> str | None:
    raise NotImplementedError


def write_active(file: Path, name: str, session_key: str | None = None) -> None:
    raise NotImplementedError


def clear_active(file: Path, session_key: str | None = None) -> None:
    raise NotImplementedError
