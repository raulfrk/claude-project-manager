"""pid-scoped read/write of ~/.claude/proj-session.yaml for multi-session safety."""

from __future__ import annotations

import datetime
import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path

import psutil
import yaml

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


def _atomic_write(target: Path, content: str) -> None:
    """Atomically write content to target via tmpfile + rename."""
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=target.parent, prefix=f".{target.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        Path(tmp).replace(target)
    except Exception:
        with suppress(FileNotFoundError):
            Path(tmp).unlink()
        raise


def _gc_dead_pids(data: dict[str, object]) -> dict[str, object]:
    """Remove active_by_claude_pid entries whose pid does not exist."""
    entries = data.get("active_by_claude_pid") or {}
    if not isinstance(entries, dict):
        return data
    alive: dict[str, object] = {}
    for key, entry in entries.items():
        try:
            pid_int = int(key)
        except (TypeError, ValueError):
            continue
        if psutil.pid_exists(pid_int):
            alive[str(key)] = entry
    data["active_by_claude_pid"] = alive
    return data


def write_active(file: Path, name: str, session_key: str | None = None) -> None:
    """Write active=name into the session_key's slot, preserving other sessions.

    Runs a GC pass (prune dead pids) on the way through. Uses atomic rename.
    Migrates v1 files to v2 as part of the write.
    """
    key = session_key if session_key is not None else get_claude_session_key()
    raw = _load_raw(file) or {}
    raw = _migrate_if_needed(raw, key)
    raw = _gc_dead_pids(raw)
    entries = raw.get("active_by_claude_pid") or {}
    if not isinstance(entries, dict):
        entries = {}
    entries[key] = {"active": name, "last_seen": _now_iso()}
    new_data: dict[str, object] = {"schema_version": 2, "active_by_claude_pid": entries}
    _atomic_write(file, yaml.safe_dump(new_data, sort_keys=False))


def clear_active(file: Path, session_key: str | None = None) -> None:
    """Remove session_key's entry from the file, preserving other sessions.

    No-op if the file doesn't exist. Leaves an empty active_by_claude_pid map
    behind when the last entry is cleared (schema stays intact for readers).
    """
    key = session_key if session_key is not None else get_claude_session_key()
    raw = _load_raw(file)
    if raw is None:
        return
    raw = _migrate_if_needed(raw, key)
    raw = _gc_dead_pids(raw)
    raw_entries = raw.get("active_by_claude_pid")
    entries: dict[str, object] = raw_entries if isinstance(raw_entries, dict) else {}
    entries.pop(key, None)
    new_data: dict[str, object] = {"schema_version": 2, "active_by_claude_pid": entries}
    _atomic_write(file, yaml.safe_dump(new_data, sort_keys=False))
