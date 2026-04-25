# Session-Key EXECPATH Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the cmdline-regex matcher + marker-file resolver with an EXECPATH-based ancestor walk that doesn't hardcode binary names and doesn't need any on-disk markers.

**Architecture:** New `get_claude_session_key()` reads `CLAUDE_CODE_EXECPATH` env var and matches it against ancestor process exe paths via `psutil.Process.exe()`. Two stages: direct-parent fast path (MCP servers) → ancestor walk (hooks via uv/bash). Removes ~150 lines of marker/regex/NS-inode code. Tracking todo: 754.

**Tech Stack:** Python (psutil, pathlib, os), pytest with monkeypatch.

**Spec:** `docs/superpowers/specs/2026-04-25-session-key-execpath-resolver-design.md`

---

## File Structure

| File | Responsibility | Action |
|------|----------------|--------|
| `plugins/_shared/session_key/session_key.py` | Resolver + read/write/clear active-project YAML | Rewrite resolver, delete marker/regex helpers, add legacy-cleanup-once in write_active |
| `plugins/_shared/session_key/__init__.py` | Public re-exports | Drop `write_session_marker` / `remove_session_marker` |
| `plugins/proj/server/server/cli.py` | SessionStart/SessionEnd hook entry points | Drop import + 2 marker call sites |
| `plugins/_shared/tests/test_session_key.py` | Unit tests | Rewrite `TestGetClaudeSessionKey`; drop `TestSessionMarker`; keep read/write/clear classes; add legacy-cleanup test in `TestWriteActive` |

Out-of-scope (different concerns, leave alone):
- `installer/flow/kill_stale.py` — has its own `_DEFAULT_MATCHER` for SIGTERM-targeting Claude Code processes; not the session-key resolver.
- `installer/tests/test_kill_stale.py` — tests kill_stale's matcher, not session_key.

---

## Task 1: Resolver test rewrite (red)

**Files:**
- Modify: `plugins/_shared/tests/test_session_key.py`

Rewrite `TestGetClaudeSessionKey` for the new resolver. Drop `TestSessionMarker` entirely. Keep `TestReadActive`, `TestWriteActive`, `TestClearActive` untouched (they don't reference the resolver internals or the marker functions).

- [ ] **Step 1: Replace `TestGetClaudeSessionKey` and delete `TestSessionMarker`**

Open `plugins/_shared/tests/test_session_key.py`. Replace lines 34-239 (the `TestGetClaudeSessionKey` class through end of `TestSessionMarker` class) with this new `TestGetClaudeSessionKey` class:

```python
class TestGetClaudeSessionKey:
    """EXECPATH-based ancestor-walk resolver tests.

    The resolver matches ancestor processes by canonical exe path
    (CLAUDE_CODE_EXECPATH realpath) — no cmdline regex, no marker files.
    """

    def test_falls_back_to_own_pid_when_execpath_unset(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from session_key.session_key import get_claude_session_key

        monkeypatch.delenv("CLAUDE_CODE_EXECPATH", raising=False)
        assert get_claude_session_key() == str(os.getpid())

    def test_direct_parent_match_returns_ppid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Fast path: os.getppid()'s exe matches EXECPATH → return ppid."""
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 1234)

        fake_parent = _FakeProc(pid=1234, exe="/usr/bin/claude")
        # psutil.Process(1234).exe() must return the EXECPATH for the fast path.
        monkeypatch.setattr(sk.psutil, "Process", lambda pid=None: fake_parent)
        # realpath is identity for these absolute paths
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        assert sk.get_claude_session_key() == "1234"

    def test_mid_chain_ancestor_match(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Direct parent doesn't match; an ancestor higher in the chain does."""
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        # Direct parent is uv (no match); two hops up is claude.
        monkeypatch.setattr(sk.os, "getppid", lambda: 9001)
        uv_proc = _FakeProc(pid=9001, exe="/usr/bin/uv")
        bash_proc = _FakeProc(pid=9000, exe="/bin/bash")
        claude_proc = _FakeProc(pid=8999, exe="/usr/bin/claude")

        # Process(ppid=9001) returns uv_proc; Process() (no arg) returns self
        # whose .parents() yields [uv, bash, claude].
        def fake_process(pid=None):
            if pid == 9001:
                return uv_proc
            return _FakeProc(pid=os.getpid(), parents_=[uv_proc, bash_proc, claude_proc])

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        assert sk.get_claude_session_key() == "8999"

    def test_no_ancestor_matches_falls_back_to_own_pid(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 5000)
        bash_proc = _FakeProc(pid=5000, exe="/bin/bash")
        sh_proc = _FakeProc(pid=4999, exe="/bin/sh")

        def fake_process(pid=None):
            if pid == 5000:
                return bash_proc
            return _FakeProc(pid=os.getpid(), parents_=[bash_proc, sh_proc])

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        assert sk.get_claude_session_key() == str(os.getpid())

    def test_no_such_process_mid_walk_continues(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One ancestor raises NoSuchProcess; walk continues to find next match."""
        from session_key import session_key as sk

        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 7000)

        # Direct parent: bash (no match). One ancestor raises; the next matches.
        bash_proc = _FakeProc(pid=7000, exe="/bin/bash")
        dead_proc = _FakeProc(pid=6999, exe_raises=True)
        claude_proc = _FakeProc(pid=6998, exe="/usr/bin/claude")

        def fake_process(pid=None):
            if pid == 7000:
                return bash_proc
            return _FakeProc(pid=os.getpid(), parents_=[bash_proc, dead_proc, claude_proc])

        monkeypatch.setattr(sk.psutil, "Process", fake_process)
        monkeypatch.setattr(sk.os.path, "realpath", lambda p: p)

        assert sk.get_claude_session_key() == "6998"

    def test_realpath_normalization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """EXECPATH and ancestor exe both go through realpath() — symlinks resolve."""
        from session_key import session_key as sk

        # EXECPATH is /usr/bin/claude (a symlink); realpath → /opt/claude/bin/claude.
        monkeypatch.setenv("CLAUDE_CODE_EXECPATH", "/usr/bin/claude")
        monkeypatch.setattr(sk.os, "getppid", lambda: 4242)
        parent = _FakeProc(pid=4242, exe="/usr/bin/claude")  # also a symlink

        monkeypatch.setattr(sk.psutil, "Process", lambda pid=None: parent)

        def fake_realpath(p: str) -> str:
            if p == "/usr/bin/claude":
                return "/opt/claude/bin/claude"
            return p

        monkeypatch.setattr(sk.os.path, "realpath", fake_realpath)

        assert sk.get_claude_session_key() == "4242"
```

Update `_FakeProc` (top of file, line 17) to support exe(), exe_raises, and parents_:

```python
class _FakeProc:
    """Minimal psutil.Process stub for resolver tests."""

    def __init__(
        self,
        pid: int,
        exe: str = "",
        exe_raises: bool = False,
        parents_: list["_FakeProc"] | None = None,
    ) -> None:
        self.pid = pid
        self._exe = exe
        self._exe_raises = exe_raises
        self._parents = parents_ or []

    def exe(self) -> str:
        if self._exe_raises:
            import psutil
            raise psutil.NoSuchProcess(self.pid)
        return self._exe

    def parents(self) -> list["_FakeProc"]:
        return self._parents

    # Legacy fields kept for any pre-existing tests that still reference them.
    def cmdline(self) -> list[str]:
        return []
```

Drop `TestSessionMarker` entirely (lines 170-239). The class and all its tests go away.

- [ ] **Step 2: Run the rewritten tests to verify they fail**

Run: `uv run --no-sync pytest plugins/_shared/tests/test_session_key.py::TestGetClaudeSessionKey -v`

Expected: tests FAIL — current `get_claude_session_key()` doesn't read `CLAUDE_CODE_EXECPATH` or use `psutil.Process.exe()`. The first test (EXECPATH unset) might pass coincidentally because the current resolver also falls back to `os.getpid()` when nothing matches; the other 5 will fail with assertion mismatches.

Also run: `uv run --no-sync pytest plugins/_shared/tests/test_session_key.py -v`

Expected: `TestSessionMarker` collection fails (class deleted) — pytest reports `class TestSessionMarker not collected` or just shows reduced count. `TestReadActive`, `TestWriteActive`, `TestClearActive` should still all pass (they don't depend on resolver internals).

- [ ] **Step 3: Commit (red)**

```bash
git add plugins/_shared/tests/test_session_key.py
git commit -m "test(session_key): pin EXECPATH-based resolver behavior (red)

Replace TestGetClaudeSessionKey with 6 tests for the candidate-free
resolver: EXECPATH unset fallback, direct parent fast path, mid-chain
ancestor match, no match fallback, NoSuchProcess mid-walk, realpath
normalization. Drop TestSessionMarker entirely (marker functions
removed in next task).

Tests fail until the resolver is rewritten.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Resolver rewrite (green)

**Files:**
- Modify: `plugins/_shared/session_key/session_key.py`

Replace the resolver and delete the marker / regex / NS-inode helpers. Add a one-shot legacy-marker-dir cleanup invoked from `write_active`.

- [ ] **Step 1: Rewrite `session_key.py`**

Replace `plugins/_shared/session_key/session_key.py` with this content (preserving the file's overall structure for `read_active`/`write_active`/`clear_active`):

```python
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
    """Return the calling process's Claude Code ancestor pid as a string.

    Uses CLAUDE_CODE_EXECPATH (an env var Claude Code injects into every
    subprocess) to identify the Claude binary by canonical exe path. Two
    stages:

    1. Fast path — os.getppid()'s exe matches EXECPATH (covers stdio MCP
       servers Claude spawns directly).
    2. General path — walk psutil.Process().parents(), return the first
       whose exe path matches (covers hook subprocesses via bash/uv/etc.).

    Falls back to os.getpid() when EXECPATH is absent (tests, non-Claude
    environments) — same fallback semantics as the previous resolver.
    """
    expected_raw = os.environ.get("CLAUDE_CODE_EXECPATH", "")
    if expected_raw:
        expected = os.path.realpath(expected_raw)

        # Fast path: direct parent.
        try:
            ppid = os.getppid()
            parent_exe = os.path.realpath(psutil.Process(ppid).exe())
            if parent_exe == expected:
                return str(ppid)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass

        # General path: walk the ancestor chain.
        try:
            for ancestor in psutil.Process().parents():
                try:
                    if os.path.realpath(ancestor.exe()) == expected:
                        return str(ancestor.pid)
                except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                    continue
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass

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
```

Note what's gone: `re` import, `_DEFAULT_MATCHER`, `_get_matcher`, `_cmdline_str`, `_read_pid_ns_inode`, `_ancestor_pids`, `_read_marker_pids`, `_gc_marker_dir`, `write_session_marker`, `remove_session_marker`, `_MARKER_DIR`. New: `shutil` import, `_LEGACY_MARKER_DIR`, `_legacy_cleanup_done`, `_cleanup_legacy_marker_dir_once`.

- [ ] **Step 2: Run resolver tests to verify green**

Run: `uv run --no-sync pytest plugins/_shared/tests/test_session_key.py::TestGetClaudeSessionKey -v`

Expected: all 6 tests pass.

Run: `uv run --no-sync pytest plugins/_shared/tests/test_session_key.py -v`

Expected: full file green except the (now-deleted) `TestSessionMarker` class isn't collected — pytest reports the new total. `TestReadActive` (8), `TestWriteActive` (6), `TestClearActive` (3), `TestGetClaudeSessionKey` (6) = 23 total.

- [ ] **Step 3: Commit (green)**

```bash
git add plugins/_shared/session_key/session_key.py
git commit -m "feat(session_key): EXECPATH-based ancestor-walk resolver

Replace cmdline-regex matcher + marker-file mechanism with a candidate-
free design that uses CLAUDE_CODE_EXECPATH (set by Claude Code in every
subprocess) to identify Claude's binary by canonical exe path.

Two stages:
- Fast path: os.getppid()'s exe matches EXECPATH (MCP servers).
- General path: walk psutil.Process().parents() (hook subprocesses via
  uv/bash/etc.).

Falls back to os.getpid() when EXECPATH is absent (tests, non-Claude
environments) — same fallback as before.

Deleted: _DEFAULT_MATCHER, _get_matcher, _cmdline_str, _ancestor_pids,
_read_marker_pids, _gc_marker_dir, _read_pid_ns_inode,
write_session_marker, remove_session_marker, _MARKER_DIR.

Added: one-shot legacy marker-dir cleanup inside write_active.

Tracking: todo 754. No public API rename — get_claude_session_key,
read_active, write_active, clear_active keep their signatures.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Update `__init__.py` re-exports

**Files:**
- Modify: `plugins/_shared/session_key/__init__.py`

The package's `__init__.py` re-exports `write_session_marker` and `remove_session_marker`. After Task 2, those names don't exist. Imports of the package break.

- [ ] **Step 1: Drop the marker-function re-exports**

Replace `plugins/_shared/session_key/__init__.py` with:

```python
"""Session-scoped active-project state shared between proj and wiki plugins.

Exposes pid-keyed read/write/clear over ~/.claude/proj-session.yaml v2 schema
so concurrent Claude Code sessions don't clobber each other.
"""

from __future__ import annotations

from session_key.session_key import (
    clear_active,
    get_claude_session_key,
    read_active,
    write_active,
)

__all__ = [
    "clear_active",
    "get_claude_session_key",
    "read_active",
    "write_active",
]
```

- [ ] **Step 2: Run the package's import test (the test file imports the package)**

Run: `uv run --no-sync pytest plugins/_shared/tests/test_session_key.py -v`

Expected: still green (23 tests). The `__init__.py` import path is exercised by the test file's `from session_key.session_key import ...` lines.

Also run: `uv run --no-sync python -c "from session_key import clear_active, get_claude_session_key, read_active, write_active; print('ok')"`

Expected: prints `ok` with no ImportError.

- [ ] **Step 3: Commit**

```bash
git add plugins/_shared/session_key/__init__.py
git commit -m "refactor(session_key): drop marker-function re-exports

write_session_marker and remove_session_marker were deleted in the
EXECPATH resolver refactor; remove them from __init__.py too.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Drop marker calls from proj cli.py

**Files:**
- Modify: `plugins/proj/server/server/cli.py`

The proj plugin's SessionStart hook (`cmd_session_start`, line 181) and SessionEnd hook (`cmd_session_end`, around line 266) call `write_session_marker` / `remove_session_marker`. With markers gone, those calls become broken imports.

- [ ] **Step 1: Drop the import**

Edit line 16 of `plugins/proj/server/server/cli.py`. Find:

```python
from session_key import remove_session_marker, write_session_marker
```

Delete that line entirely.

- [ ] **Step 2: Drop `write_session_marker` call in `cmd_session_start`**

Find lines 188-193 (around the marker write):

```python
    # Marker write happens FIRST, regardless of project config state. This
    # records the (claude_pid, ns_inode) tuple that MCP servers later use to
    # resolve their session_key without cmdline-regex guessing. PPID is
    # Claude's pid because this CLI is a direct child of the SessionStart hook
    # which itself was spawned by Claude Code.
    write_session_marker(claude_pid=os.getppid(), cwd=cwd)
```

Delete the whole 6-line block. The function body now starts directly with the `if not storage.config_exists():` check.

- [ ] **Step 3: Drop `remove_session_marker` call in `cmd_session_end`**

Find line 266 (or wherever `remove_session_marker(claude_pid=os.getppid())` lives). Delete that line.

- [ ] **Step 4: Verify proj plugin imports cleanly**

Run: `uv run --no-sync python -c "from server import cli; print('ok')"` — but only if proj's server/ is importable from the project root. If not (the package layout requires being inside the plugin's server dir or having it on PYTHONPATH), use:

```bash
PYTHONPATH=plugins/proj/server uv run --no-sync python -c "from server import cli; print('ok')"
```

Expected: prints `ok` with no ImportError.

- [ ] **Step 5: Run proj plugin tests**

Run: `uv run --no-sync pytest plugins/proj -x` (some test files may need PYTHONPATH; the cross-plugin integration test from prior session covers per-plugin sys.path).

Expected: green. If any test asserts `cmd_session_start` writes a marker, that test gets an updated assertion in this same task — drop the marker-side-effect assertion.

If a test breaks because it expected a marker file to appear, edit that test to drop the assertion. Stage that test file in the same commit.

- [ ] **Step 6: Commit**

```bash
git add plugins/proj/server/server/cli.py
# Also `git add plugins/proj/...test_file...` if a test was edited
git commit -m "refactor(proj/cli): drop marker write/remove from session hooks

write_session_marker and remove_session_marker were deleted in the
EXECPATH resolver refactor. cmd_session_start no longer writes the
~/.claude/proj-session-markers/<pid>.yaml file; cmd_session_end no
longer removes it. The new resolver in plugins/_shared/session_key
finds Claude's pid via CLAUDE_CODE_EXECPATH ancestor walk without any
on-disk marker.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Test legacy-marker-dir cleanup runs once

**Files:**
- Modify: `plugins/_shared/tests/test_session_key.py`

Add a test inside `TestWriteActive` that verifies `_cleanup_legacy_marker_dir_once` is invoked the first time `write_active` runs and skipped on subsequent calls.

- [ ] **Step 1: Add the test inside `TestWriteActive`**

Append to the `TestWriteActive` class (currently around line 315, ends near line 396):

```python
    def test_write_active_cleans_legacy_marker_dir_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """First write_active call removes ~/.claude/proj-session-markers/.

        Subsequent calls in the same process skip the cleanup (guarded by a
        module-level flag).
        """
        from session_key import session_key as sk

        # Reset the module-level guard so this test isn't order-dependent.
        monkeypatch.setattr(sk, "_legacy_cleanup_done", False)

        # Synthetic legacy marker dir under tmp_path.
        legacy = tmp_path / "proj-session-markers"
        legacy.mkdir()
        (legacy / "1234.yaml").write_text("ns_inode: 0\nstarted: '2026-01-01T00:00:00+00:00'\n")
        monkeypatch.setattr(sk, "_LEGACY_MARKER_DIR", legacy)

        target = tmp_path / "proj-session.yaml"
        sk.write_active(target, "proj-x", session_key="100")

        # First call: legacy dir gone.
        assert not legacy.exists()

        # Recreate it; a second call should NOT remove it (guard prevents).
        legacy.mkdir()
        (legacy / "5678.yaml").write_text("ns_inode: 0\n")
        sk.write_active(target, "proj-y", session_key="100")
        assert legacy.exists(), (
            "Second write_active should be a no-op for legacy cleanup"
        )
```

- [ ] **Step 2: Run the test**

Run: `uv run --no-sync pytest plugins/_shared/tests/test_session_key.py::TestWriteActive::test_write_active_cleans_legacy_marker_dir_once -v`

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add plugins/_shared/tests/test_session_key.py
git commit -m "test(session_key): legacy marker dir cleanup runs once per process

Verifies _cleanup_legacy_marker_dir_once is called by write_active on
first invocation (rmtree's the v1 marker dir) and skipped on subsequent
calls in the same process.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: Full suite + push

**Files:** none modified.

- [ ] **Step 1: Run fast suite**

Run: `uv run --no-sync pytest installer/tests --ignore=installer/tests/e2e -x`

Expected: 744+ pass (no regression).

- [ ] **Step 2: Run _shared tests**

Run: `uv run --no-sync pytest plugins/_shared/tests -x`

Expected: 24 pass (23 prior + 1 legacy-cleanup test).

- [ ] **Step 3: Run proj tests**

Run: `uv run --no-sync pytest plugins/proj -x` (with appropriate PYTHONPATH if needed; check existing CI or just script for the pattern).

Expected: green. Any test broken by the marker-call removal already fixed in Task 4.

- [ ] **Step 4: Run cross-plugin integration test (slow)**

Run: `uv run --no-sync pytest installer/tests -m slow --ignore=installer/tests/e2e -x`

Expected: 9 pass (cross-plugin integration test still green — the new resolver doesn't change MCP server behavior at the plugin-boundary level).

- [ ] **Step 5: Push to dev**

```bash
git push origin dev
```

Expected: 5 new commits land (1 spec + 1 plan from earlier + 5 impl commits). Watch CI:

```bash
gh run list --branch dev --limit 1
```

---

## Self-Review

**Spec coverage**

| Spec section | Task |
|---|---|
| New resolver: fast path + general walk + fallback | Task 2 (impl) |
| Delete: _DEFAULT_MATCHER, _get_matcher, _cmdline_str, _ancestor_pids, _read_marker_pids, _gc_marker_dir, _read_pid_ns_inode, write_session_marker, remove_session_marker, _MARKER_DIR, env handling | Task 2 |
| Keep: read_active, write_active, clear_active, helpers | Task 2 (preserved verbatim) |
| One-shot legacy marker-dir cleanup | Task 2 (impl) + Task 5 (test) |
| Drop import + 2 calls in cli.py | Task 4 |
| `__init__.py` re-export update | Task 3 |
| Resolver test rewrite (6 cases) | Task 1 |
| Verification: pytest + manual reinstall | Task 6 + spec's manual section (out of plan scope per spec) |

No gaps.

**Placeholder scan**

No "TBD" / "TODO" / "Add appropriate" / "Similar to Task N" / "..." patterns. Each step has exact code or exact command + expected output. The cli.py edit in Task 4 references line numbers — they're approximate ("around line 188-193", "line 266 or wherever") because pre-edit line numbers can drift; the textual anchor is unambiguous (the `write_session_marker` call is the only one in the file).

**Type/name consistency**

`get_claude_session_key()` returns `str` everywhere. `_FakeProc` test stub matches the methods used by the resolver: `pid`, `exe()`, `parents()`. Module-level constants `_LEGACY_MARKER_DIR` and `_legacy_cleanup_done` are referenced consistently in Task 2's impl and Task 5's test (via `monkeypatch.setattr(sk, "_legacy_cleanup_done", False)` and `monkeypatch.setattr(sk, "_LEGACY_MARKER_DIR", legacy)`). The `from session_key import session_key as sk` import shape is repeated across tests so they all access the same module-level state.

Plan is executable as-is.
