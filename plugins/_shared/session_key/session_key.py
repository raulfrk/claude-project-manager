"""pid-scoped read/write of ~/.claude/proj-session.yaml for multi-session safety."""

from __future__ import annotations

import datetime
import os
import re
from typing import TYPE_CHECKING

import psutil
import yaml

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
    """Read active project for the given session_key from v2 file.

    Returns None if file missing, malformed, or the key is absent / has no
    `active` field. Uses `get_claude_session_key()` when session_key is None.
    """
    key = session_key if session_key is not None else get_claude_session_key()
    data = _load_raw(file)
    if data is None:
        return None
    data = _migrate_if_needed(data, key)
    entries = data.get("active_by_claude_pid") or {}
    if not isinstance(entries, dict):
        return None
    entry = entries.get(key)
    if not isinstance(entry, dict):
        return None
    value = entry.get("active")
    if not value:
        return None
    return str(value)


def _load_raw(file: Path) -> dict[str, object] | None:
    """Load raw YAML dict from file. Returns None on missing/malformed."""
    if not file.exists():
        return None
    try:
        with file.open() as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError:
        return None
    if not isinstance(data, dict):
        return None
    return data


def _migrate_if_needed(data: dict[str, object], session_key: str) -> dict[str, object]:
    """Migrate v1 (flat `active`) into v2 structure in-memory. Does NOT write.

    If file has no schema_version but has a v1 `active` scalar, inject it into
    the current session's slot. Callers that want to persist the migration
    should re-write via write_active. Returns data unchanged if already v2 or
    if no v1 content is present.
    """
    if data.get("schema_version") == 2:
        return data
    legacy = data.get("active")
    if not legacy:
        return data
    # Synthesize a v2 in-memory view for the current session.
    return {
        "schema_version": 2,
        "active_by_claude_pid": {
            session_key: {"active": str(legacy), "last_seen": _now_iso()},
        },
    }


def _now_iso() -> str:
    """Return current UTC time in ISO 8601 seconds precision."""
    return datetime.datetime.now(datetime.UTC).replace(microsecond=0).isoformat()


def write_active(file: Path, name: str, session_key: str | None = None) -> None:
    raise NotImplementedError


def clear_active(file: Path, session_key: str | None = None) -> None:
    raise NotImplementedError
