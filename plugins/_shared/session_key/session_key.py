"""pid-scoped read/write of ~/.claude/proj-session.yaml for multi-session safety.

Session-key resolution uses CLAUDE_CODE_EXECPATH (set by Claude Code in every
subprocess) to identify Claude's binary by canonical exe path. No cmdline
regex, no marker files, no namespace-inode tracking — Claude Code self-
identifies via its own env var.
"""

from __future__ import annotations

import datetime
import logging
import os
import shutil
import tempfile
from contextlib import suppress
from pathlib import Path

import psutil
import yaml

log = logging.getLogger(__name__)

# Legacy marker dir from the pre-EXECPATH resolver. Cleaned up once on first
# write_active() per process so users don't accumulate stale yaml files.
_LEGACY_MARKER_DIR: Path = Path.home() / ".claude" / "proj-session-markers"
_legacy_cleanup_done: bool = False


def get_claude_session_key() -> str:
    """Return the calling process's outermost Claude Code ancestor pid as a string.

    Walks ``psutil.Process().parents()`` and returns the OUTERMOST ancestor
    whose canonical exe path matches CLAUDE_CODE_EXECPATH (the env var Claude
    Code injects into every subprocess).

    Outermost-match — not first-match — because Claude self-forks for hook
    execution. The process tree under a SessionStart hook is::

        claude-bin (OUTER, long-lived, parents MCP servers)
         └─ claude-bin (INNER, transient fork for hook execution)
             └─ <shell or interpreter chain>
                 └─ python (cli.py)

    Both INNER and OUTER match EXECPATH. Only OUTER is authoritative for
    session state — it parents the MCP servers that read what hooks write.
    Returning INNER's pid (first-match) causes hooks and MCP servers to
    disagree on the session key, breaking ``proj-session.yaml`` lookups.

    No fast path: a single walk handles both MCP servers (one matching
    ancestor) and hooks (multiple matching ancestors). ``parents()`` is
    microseconds-fast.

    Iteration-order invariant: ``psutil.Process().parents()`` yields ancestors
    immediate-first (ascending toward init), so the LAST recorded match is the
    outermost. The ``test_outermost_match_*`` regression tests pin this; if
    upstream ever inverts the order, those tests fail loud.

    EXECPATH-unset fallback: returns ``os.getppid()``. This handles plugin MCP
    servers, which Claude Code launches directly via ``.mcp.json`` ``command:
    bash start.sh ...`` without propagating CLAUDE_CODE_EXECPATH (asymmetry
    with hook subprocesses, where it IS set). The MCP server's parent IS the
    long-lived claude-bin that owns the session, so ``getppid()`` returns the
    same pid the EXECPATH walk would have returned for a hook subprocess.
    For non-Claude contexts (tests run from a shell, standalone CLI), ppid is
    the launcher — still a stable session-like key, just a different one.

    Walk-failed fallback: ``os.getpid()`` when EXECPATH IS set but no ancestor
    matches (anomaly — process tree was rewritten, or test mocks return an
    empty/non-matching chain).
    """
    expected_raw = os.environ.get("CLAUDE_CODE_EXECPATH", "")
    if not expected_raw:
        return str(os.getppid())
    expected = os.path.realpath(expected_raw)

    last_match: int | None = None
    try:
        for ancestor in psutil.Process().parents():
            try:
                if os.path.realpath(ancestor.exe()) == expected:
                    last_match = ancestor.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                continue
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        pass

    if last_match is not None:
        return str(last_match)
    return str(os.getpid())


def _cleanup_legacy_marker_dir_once() -> None:
    """Remove the v1 marker dir on first call per process. Best-effort.

    The v1 resolver wrote ``~/.claude/proj-session-markers/<pid>.yaml`` files
    to support cross-NS sandboxed sessions. The new EXECPATH resolver doesn't
    need them; this clears the leak so users don't accumulate stale yaml.
    """
    global _legacy_cleanup_done
    if _legacy_cleanup_done:
        return
    _legacy_cleanup_done = True
    if _LEGACY_MARKER_DIR.is_dir():
        with suppress(OSError):
            shutil.rmtree(_LEGACY_MARKER_DIR)


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
    Migrates v1 files to v2 as part of the write. Cleans up the legacy marker
    directory once per process on first call.

    Concurrency note: this is a read-modify-write sequence without a file lock.
    Two sessions writing simultaneously could race — one write may overwrite the
    other's just-persisted entry. Per design (Approach A), this is accepted:
    the operation is user-triggered (`/proj:load`, `/proj:archive`) and a
    collision requires two such commands within microseconds of each other.
    If tighter guarantees are needed in the future, add `fcntl.flock` here.
    """
    _cleanup_legacy_marker_dir_once()
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
