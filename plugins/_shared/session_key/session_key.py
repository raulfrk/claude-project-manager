"""pid-scoped read/write of ~/.claude/proj-session.yaml for multi-session safety.

Session-key resolution prefers hook-written marker files (reliable across all
install styles + safe under bwrap PID-namespace sandboxing) and falls back to
cmdline-regex ancestor matching when no markers exist (legacy mode for installs
without the proj plugin's SessionStart hook).
"""

from __future__ import annotations

import datetime
import logging
import os
import re
import tempfile
from contextlib import suppress
from pathlib import Path

import psutil
import yaml

log = logging.getLogger(__name__)

_DEFAULT_MATCHER: re.Pattern[str] = re.compile(
    r"(?:^|/)claude(?:-code)?(?:\s|$)|"  # claude / claude-code as a token
    r"node\s+\S*claude-code\S*"  # node /path/.../claude-code/cli.js style
)

# Marker dir written by the proj plugin's SessionStart hook. Each Claude Code
# session writes <claude-pid>.yaml with its NS inode; SessionEnd removes it.
_MARKER_DIR: Path = Path.home() / ".claude" / "proj-session-markers"


def _get_matcher() -> re.Pattern[str]:
    """Return the cmdline matcher regex for Claude Code ancestor detection.

    Default matches `claude` / `claude-code` binary paths and node-direct
    invocations (`node /path/.../claude-code/cli.js`). Override via env var
    CPM_CLAUDE_CODE_CMDLINE_MATCHER.
    """
    custom = os.getenv("CPM_CLAUDE_CODE_CMDLINE_MATCHER")
    if custom:
        return re.compile(custom)
    return _DEFAULT_MATCHER


def _cmdline_str(parts: list[str]) -> str:
    """Render cmdline list as a single space-joined string for regex matching."""
    return " ".join(parts)


def _read_pid_ns_inode() -> int:
    """Return the inode of /proc/self/ns/pid, or 0 if unavailable.

    The inode is a stable identifier for the current process's PID namespace.
    Two processes in different namespaces (e.g. separate bwrap containers)
    have different inodes; processes in the same namespace share one.
    """
    try:
        return Path("/proc/self/ns/pid").stat().st_ino
    except OSError:
        return 0


def _ancestor_pids() -> list[int]:
    """Return ancestor pids (immediate parent first), or [] if walk fails."""
    try:
        return [a.pid for a in psutil.Process().parents()]
    except Exception:
        return []


def _read_marker_pids(ns_inode: int) -> set[int]:
    """Return pids from marker files matching the given NS inode.

    Returns empty set if marker dir missing, no files, or no NS-matching
    entries. Silently skips files with malformed YAML, missing ns_inode,
    or non-integer filenames.
    """
    if not _MARKER_DIR.is_dir():
        return set()
    pids: set[int] = set()
    for entry in _MARKER_DIR.iterdir():
        if entry.suffix != ".yaml":
            continue
        try:
            pid = int(entry.stem)
        except ValueError:
            continue
        try:
            data = yaml.safe_load(entry.read_text())
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        marker_ns = data.get("ns_inode")
        # ns_inode == 0 means the writer couldn't read /proc/self/ns/pid;
        # treat as wildcard so non-Linux + readonly /proc setups still work.
        if marker_ns in (0, ns_inode) or ns_inode == 0:
            pids.add(pid)
    return pids


def get_claude_session_key() -> str:
    """Return Claude Code ancestor pid (as str) for the current process.

    Resolution order:
    1. Read hook-written marker files at ~/.claude/proj-session-markers/.
       For each ancestor pid, check if a marker file exists (filtered by NS
       inode) — return the first match. This is the reliable path: the
       marker is written by Claude Code's SessionStart hook whose PPID *is*
       Claude's pid, so no cmdline guessing is involved.
    2. Walk the ppid chain via psutil, returning the first ancestor whose
       cmdline matches the matcher regex. Used when the marker dir is
       missing/empty (fresh install, no proj plugin, or hook not yet run).
    3. Fall back to the current process pid if neither path finds a Claude
       ancestor (single-process / test scenarios).
    """
    ns_inode = _read_pid_ns_inode()
    marker_pids = _read_marker_pids(ns_inode)
    ancestors = _ancestor_pids()
    if marker_pids:
        for pid in ancestors:
            if pid in marker_pids:
                return str(pid)
    matcher = _get_matcher()
    try:
        for ancestor in psutil.Process().parents():
            if matcher.search(_cmdline_str(ancestor.cmdline())):
                return str(ancestor.pid)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        pass
    return str(os.getpid())


def write_session_marker(claude_pid: int, cwd: str | None = None) -> None:
    """Record this Claude Code session in the marker directory.

    Called by the proj plugin's SessionStart hook (whose PPID is Claude's pid).
    Idempotent — overwrites any prior marker for the same pid. Best-effort:
    failures are logged + swallowed so a marker-write problem can never block
    a session start.
    """
    try:
        _MARKER_DIR.mkdir(parents=True, exist_ok=True)
        target = _MARKER_DIR / f"{claude_pid}.yaml"
        payload: dict[str, object] = {
            "ns_inode": _read_pid_ns_inode(),
            "started": _now_iso(),
        }
        if cwd:
            payload["cwd"] = cwd
        _atomic_write(target, yaml.safe_dump(payload, sort_keys=False))
        _gc_marker_dir()
    except OSError as exc:
        log.debug("session marker write failed: %s", exc)


def remove_session_marker(claude_pid: int) -> None:
    """Remove this session's marker. Called by SessionEnd. No-op if missing."""
    target = _MARKER_DIR / f"{claude_pid}.yaml"
    with suppress(FileNotFoundError):
        target.unlink()


def _gc_marker_dir() -> None:
    """Drop marker files whose pid no longer exists. Best-effort."""
    if not _MARKER_DIR.is_dir():
        return
    for entry in _MARKER_DIR.iterdir():
        if entry.suffix != ".yaml":
            continue
        try:
            pid = int(entry.stem)
        except ValueError:
            continue
        if not psutil.pid_exists(pid):
            with suppress(OSError):
                entry.unlink()


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
        try:
            f = os.fdopen(fd, "w")
        except Exception:
            os.close(fd)
            raise
        with f:
            f.write(content)
        Path(tmp).replace(target)
    except Exception:
        with suppress(FileNotFoundError):
            Path(tmp).unlink()
        raise


def _gc_dead_pids(data: dict[str, object]) -> dict[str, object]:
    """Remove active_by_claude_pid entries whose pid does not exist.

    Non-integer keys are silently dropped — all valid session keys produced by
    `get_claude_session_key` are integer pid strings; any non-numeric key has
    been corrupted and should not be preserved.

    Mutates `data` in place AND returns it (callers typically discard the
    return value).
    """
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

    Concurrency note: this is a read-modify-write sequence without a file lock.
    Two sessions writing simultaneously could race — one write may overwrite the
    other's just-persisted entry. Per design (Approach A), this is accepted:
    the operation is user-triggered (`/proj:load`, `/proj:archive`) and a
    collision requires two such commands within microseconds of each other.
    If tighter guarantees are needed in the future, add `fcntl.flock` here.
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
