# Proj session multi-session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `~/.claude/proj-session.yaml` safe for concurrent Claude Code sessions by keying active-project state by Claude Code ancestor pid (Approach A from 2026-04-24-proj-session-multi-design.md).

**Architecture:** New shared helper `plugins/_shared/session_key/` owns the v2 file schema, the ppid-chain walk, and GC. proj `state.py` and wiki `scope.py` both call it; neither duplicates the format logic. Schema v2: `{schema_version: 2, active_by_claude_pid: {<pid>: {active, last_seen}}}`. v1 files auto-migrate on first read into the current session's slot. GC prunes dead pids on read.

**Tech Stack:** Python 3.12+, `psutil` (new dep on shared package), `pyyaml` (already present), pytest + pytest-mock + freezegun for tests. Files gated on the existing `claude-hook-transport` shared wheel; both proj and wiki already depend on it transitively.

---

## File Structure

**Create:**
- `plugins/_shared/session_key/__init__.py` — public API re-exports
- `plugins/_shared/session_key/session_key.py` — core logic (ppid walk, schema v2 R/W, migration, GC)
- `plugins/_shared/tests/test_session_key.py` — unit tests for the shared helper

**Modify:**
- `plugins/_shared/pyproject.toml` — add `psutil>=5.9` dep; add `session_key` to wheel packages + coverage targets
- `plugins/proj/server/server/lib/state.py` — delegate file R/W to `session_key`; keep in-memory cache
- `plugins/proj/server/tests/test_state.py` — update fixtures + tests for v2 file layout
- `plugins/wiki/server/server/tools/scope.py` — delegate file read to `session_key`
- `plugins/wiki/server/tests/test_scope.py` — update test fixture writer to emit v2 layout; add multi-session test
- `CLAUDE.md` (repo root) — document `proj-session.yaml` v2 format in the config-naming section

Existing `pyproject.toml` files for proj and wiki do not need dep changes — they already source `claude-hook-transport = { path = "../../_shared" }`, so adding `psutil` there flows in transitively. The `pythonpath = ["../../_shared"]` entry also already makes the new `session_key` package importable during tests.

---

## Task 1: Scaffold shared `session_key` package

**Files:**
- Create: `plugins/_shared/session_key/__init__.py`
- Create: `plugins/_shared/session_key/session_key.py`
- Modify: `plugins/_shared/pyproject.toml`

- [ ] **Step 1: Add psutil dep + register package in wheel**

In `plugins/_shared/pyproject.toml`, update the `dependencies` and `packages` lines:

```toml
[project]
name = "claude-hook-transport"
version = "0.4.18"
description = "Shared dual-transport library for MCP plugin inter-server hook communication"
requires-python = ">=3.12"
dependencies = [
    "mcp>=1.2.0",
    "httpx>=0.28",
    "psutil>=5.9",
]
```

```toml
[tool.hatch.build.targets.wheel]
packages = ["hook_transport", "hook_dispatch", "scrubbing", "test_contracts", "claudemd", "session_key"]
force-include = { "claudemd/managed_section.md" = "claudemd/managed_section.md" }
```

And extend coverage to include the new package:

```toml
addopts = ["-v", "--tb=short", "--cov=hook_transport", "--cov=hook_dispatch", "--cov=scrubbing", "--cov=claudemd", "--cov=test_contracts", "--cov=session_key", "--cov-fail-under=80"]
```

- [ ] **Step 2: Create the package files with NotImplementedError stubs**

Create `plugins/_shared/session_key/session_key.py`:

```python
"""pid-scoped read/write of ~/.claude/proj-session.yaml for multi-session safety."""

from __future__ import annotations

from pathlib import Path


def get_claude_session_key() -> str:
    raise NotImplementedError


def read_active(file: Path, session_key: str | None = None) -> str | None:
    raise NotImplementedError


def write_active(file: Path, name: str, session_key: str | None = None) -> None:
    raise NotImplementedError


def clear_active(file: Path, session_key: str | None = None) -> None:
    raise NotImplementedError
```

Create `plugins/_shared/session_key/__init__.py`:

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

- [ ] **Step 3: Sync uv.lock + verify package imports**

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi/plugins/_shared
uv sync --all-groups
uv run python -c "import session_key; print(session_key.__all__)"
```

Expected output: `['clear_active', 'get_claude_session_key', 'read_active', 'write_active']`.

- [ ] **Step 4: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi
git add plugins/_shared/pyproject.toml plugins/_shared/session_key/__init__.py plugins/_shared/session_key/session_key.py plugins/_shared/uv.lock
git commit -m "feat(session_key/724): scaffold shared session_key package"
```

---

## Task 2: Implement `get_claude_session_key` (ppid-chain walk)

**Files:**
- Create: `plugins/_shared/tests/test_session_key.py`
- Modify: `plugins/_shared/session_key/session_key.py`

- [ ] **Step 1: Write failing tests for the ppid walk**

Create `plugins/_shared/tests/test_session_key.py`:

```python
"""Unit tests for session_key helper."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from session_key import session_key as sk


class _FakeProc:
    def __init__(self, pid: int, cmdline: list[str]) -> None:
        self.pid = pid
        self._cmdline = cmdline

    def cmdline(self) -> list[str]:
        return self._cmdline


class TestGetClaudeSessionKey:
    def test_returns_ancestor_pid_when_claude_in_chain(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        own_pid = 1001
        monkeypatch.setattr(sk.os, "getpid", lambda: own_pid)

        chain = [
            _FakeProc(2002, ["uv", "run", "proj-server"]),
            _FakeProc(3003, ["/usr/local/bin/claude"]),
            _FakeProc(4004, ["/bin/zsh"]),
        ]
        fake_self = MagicMock()
        fake_self.parents.return_value = chain
        monkeypatch.setattr(sk.psutil, "Process", lambda pid=None: fake_self)

        assert sk.get_claude_session_key() == "3003"

    def test_falls_back_to_own_pid_if_no_claude_ancestor(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        own_pid = 7777
        monkeypatch.setattr(sk.os, "getpid", lambda: own_pid)

        chain = [
            _FakeProc(2002, ["uv"]),
            _FakeProc(3003, ["/bin/zsh"]),
        ]
        fake_self = MagicMock()
        fake_self.parents.return_value = chain
        monkeypatch.setattr(sk.psutil, "Process", lambda pid=None: fake_self)

        assert sk.get_claude_session_key() == str(own_pid)

    def test_matcher_env_var_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("CPM_CLAUDE_CODE_CMDLINE_MATCHER", r"^node.+myclaude$")
        monkeypatch.setattr(sk.os, "getpid", lambda: 1)

        chain = [
            _FakeProc(5005, ["/usr/bin/node /opt/myclaude"]),
        ]
        fake_self = MagicMock()
        fake_self.parents.return_value = chain
        monkeypatch.setattr(sk.psutil, "Process", lambda pid=None: fake_self)

        assert sk.get_claude_session_key() == "5005"

    def test_default_matcher_ignores_wrapper_process(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`uv run claude-server` must NOT match — only the actual `claude` binary."""
        monkeypatch.delenv("CPM_CLAUDE_CODE_CMDLINE_MATCHER", raising=False)
        monkeypatch.setattr(sk.os, "getpid", lambda: 1)

        chain = [
            _FakeProc(2002, ["uv", "run", "proj-server"]),
            _FakeProc(4004, ["/bin/zsh"]),
        ]
        fake_self = MagicMock()
        fake_self.parents.return_value = chain
        monkeypatch.setattr(sk.psutil, "Process", lambda pid=None: fake_self)

        assert sk.get_claude_session_key() == "1"  # fallback to own pid
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi/plugins/_shared
uv run pytest tests/test_session_key.py -v
```

Expected: 4 tests fail with `NotImplementedError` (or AttributeError for missing `sk.os` / `sk.psutil`).

- [ ] **Step 3: Implement `get_claude_session_key`**

Replace the stub in `plugins/_shared/session_key/session_key.py` with:

```python
"""pid-scoped read/write of ~/.claude/proj-session.yaml for multi-session safety."""

from __future__ import annotations

import os
import re
from pathlib import Path

import psutil

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
```

Keep the other three stubs (`read_active`, `write_active`, `clear_active`) as `NotImplementedError` — they come next.

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_session_key.py::TestGetClaudeSessionKey -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add plugins/_shared/session_key/session_key.py plugins/_shared/tests/test_session_key.py
git commit -m "feat(session_key/724): implement get_claude_session_key w/ ppid walk"
```

---

## Task 3: Implement `read_active` (v2 schema happy path + malformed handling)

**Files:**
- Modify: `plugins/_shared/session_key/session_key.py`
- Modify: `plugins/_shared/tests/test_session_key.py`

- [ ] **Step 1: Write failing tests for v2 read**

Append to `plugins/_shared/tests/test_session_key.py`:

```python
from pathlib import Path

import yaml


def _write_yaml(path: Path, data: dict) -> None:
    path.write_text(yaml.safe_dump(data, sort_keys=False))


class TestReadActive:
    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        assert sk.read_active(f, session_key="100") is None

    def test_v2_hit_returns_active(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        _write_yaml(
            f,
            {
                "schema_version": 2,
                "active_by_claude_pid": {
                    "100": {"active": "proj-a", "last_seen": "2026-04-24T10:00:00"},
                    "200": {"active": "proj-b", "last_seen": "2026-04-24T11:00:00"},
                },
            },
        )
        assert sk.read_active(f, session_key="100") == "proj-a"
        assert sk.read_active(f, session_key="200") == "proj-b"

    def test_v2_miss_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        _write_yaml(
            f,
            {
                "schema_version": 2,
                "active_by_claude_pid": {
                    "100": {"active": "proj-a", "last_seen": "2026-04-24T10:00:00"},
                },
            },
        )
        assert sk.read_active(f, session_key="999") is None

    def test_malformed_yaml_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        f.write_text("this: is: not: : valid")
        assert sk.read_active(f, session_key="100") is None

    def test_v2_entry_without_active_field_returns_none(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        _write_yaml(
            f,
            {
                "schema_version": 2,
                "active_by_claude_pid": {"100": {"last_seen": "2026-04-24T10:00:00"}},
            },
        )
        assert sk.read_active(f, session_key="100") is None

    def test_uses_detected_key_when_session_key_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(sk, "get_claude_session_key", lambda: "777")
        f = tmp_path / "proj-session.yaml"
        _write_yaml(
            f,
            {
                "schema_version": 2,
                "active_by_claude_pid": {"777": {"active": "auto", "last_seen": "x"}},
            },
        )
        assert sk.read_active(f) == "auto"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_session_key.py::TestReadActive -v
```

Expected: 6 tests fail with `NotImplementedError`.

- [ ] **Step 3: Implement `read_active`**

Replace the `read_active` stub in `plugins/_shared/session_key/session_key.py` with:

```python
import yaml


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


def _load_raw(file: Path) -> dict | None:
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


def _migrate_if_needed(data: dict, session_key: str) -> dict:
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
    import datetime as _dt
    return _dt.datetime.now(_dt.UTC).replace(microsecond=0).isoformat()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_session_key.py::TestReadActive -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add plugins/_shared/session_key/session_key.py plugins/_shared/tests/test_session_key.py
git commit -m "feat(session_key/724): implement read_active w/ v2 schema + malformed handling"
```

---

## Task 4: Implement `write_active` + atomic write + dead-pid GC

**Files:**
- Modify: `plugins/_shared/session_key/session_key.py`
- Modify: `plugins/_shared/tests/test_session_key.py`

- [ ] **Step 1: Write failing tests for write + GC**

Append to `plugins/_shared/tests/test_session_key.py`:

```python
class TestWriteActive:
    def test_write_creates_file_with_v2_schema(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        sk.write_active(f, "my-proj", session_key="100")

        assert f.exists()
        data = yaml.safe_load(f.read_text())
        assert data["schema_version"] == 2
        assert data["active_by_claude_pid"]["100"]["active"] == "my-proj"
        assert "last_seen" in data["active_by_claude_pid"]["100"]

    def test_write_preserves_other_sessions(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        _write_yaml(
            f,
            {
                "schema_version": 2,
                "active_by_claude_pid": {
                    "200": {"active": "other", "last_seen": "2026-04-24T10:00:00"},
                },
            },
        )
        sk.write_active(f, "mine", session_key="100")

        data = yaml.safe_load(f.read_text())
        assert data["active_by_claude_pid"]["200"]["active"] == "other"
        assert data["active_by_claude_pid"]["100"]["active"] == "mine"

    def test_write_overwrites_own_session(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        sk.write_active(f, "first", session_key="100")
        sk.write_active(f, "second", session_key="100")

        data = yaml.safe_load(f.read_text())
        assert data["active_by_claude_pid"]["100"]["active"] == "second"

    def test_gc_prunes_dead_pids_on_write(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        f = tmp_path / "proj-session.yaml"
        _write_yaml(
            f,
            {
                "schema_version": 2,
                "active_by_claude_pid": {
                    "100": {"active": "live-proj", "last_seen": "2026-04-24T10:00:00"},
                    "999": {"active": "dead-proj", "last_seen": "2026-04-20T10:00:00"},
                },
            },
        )
        # pid 100 alive, 999 dead:
        monkeypatch.setattr(sk.psutil, "pid_exists", lambda pid: pid == 100)

        sk.write_active(f, "updated", session_key="100")

        data = yaml.safe_load(f.read_text())
        assert "100" in data["active_by_claude_pid"]
        assert "999" not in data["active_by_claude_pid"]

    def test_write_migrates_v1_file(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        _write_yaml(f, {"active": "legacy-proj"})  # v1 shape
        sk.write_active(f, "new-proj", session_key="100")

        data = yaml.safe_load(f.read_text())
        assert data["schema_version"] == 2
        assert "active" not in data  # v1 key removed
        assert data["active_by_claude_pid"]["100"]["active"] == "new-proj"

    def test_write_is_atomic(self, tmp_path: Path) -> None:
        """Tmpfile should be renamed, not left behind."""
        f = tmp_path / "proj-session.yaml"
        sk.write_active(f, "proj", session_key="100")

        # No .tmp* siblings left behind:
        siblings = list(tmp_path.iterdir())
        assert all(not s.name.startswith(".proj-session.yaml.") for s in siblings)
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_session_key.py::TestWriteActive -v
```

Expected: 6 tests fail with `NotImplementedError`.

- [ ] **Step 3: Implement `write_active` + atomic helper + GC**

Add to `plugins/_shared/session_key/session_key.py`:

```python
import tempfile
from contextlib import suppress


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


def _gc_dead_pids(data: dict) -> dict:
    """Remove active_by_claude_pid entries whose pid does not exist."""
    entries = data.get("active_by_claude_pid") or {}
    if not isinstance(entries, dict):
        return data
    alive: dict = {}
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
    entries[key] = {"active": name, "last_seen": _now_iso()}
    new_data = {"schema_version": 2, "active_by_claude_pid": entries}
    _atomic_write(file, yaml.safe_dump(new_data, sort_keys=False))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_session_key.py::TestWriteActive -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add plugins/_shared/session_key/session_key.py plugins/_shared/tests/test_session_key.py
git commit -m "feat(session_key/724): implement write_active w/ atomic + dead-pid GC"
```

---

## Task 5: Implement `clear_active`

**Files:**
- Modify: `plugins/_shared/session_key/session_key.py`
- Modify: `plugins/_shared/tests/test_session_key.py`

- [ ] **Step 1: Write failing tests for clear**

Append to `plugins/_shared/tests/test_session_key.py`:

```python
class TestClearActive:
    def test_clear_removes_own_session(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        sk.write_active(f, "mine", session_key="100")
        sk.write_active(f, "theirs", session_key="200")

        sk.clear_active(f, session_key="100")

        data = yaml.safe_load(f.read_text())
        assert "100" not in data["active_by_claude_pid"]
        assert data["active_by_claude_pid"]["200"]["active"] == "theirs"

    def test_clear_on_missing_file_is_noop(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        # No file yet. Should not raise.
        sk.clear_active(f, session_key="100")
        assert not f.exists()

    def test_clear_last_session_leaves_empty_structure(self, tmp_path: Path) -> None:
        f = tmp_path / "proj-session.yaml"
        sk.write_active(f, "only", session_key="100")

        sk.clear_active(f, session_key="100")

        # File still exists w/ empty mapping — not deleted (preserves schema).
        data = yaml.safe_load(f.read_text())
        assert data["schema_version"] == 2
        assert data["active_by_claude_pid"] == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/test_session_key.py::TestClearActive -v
```

Expected: 3 tests fail with `NotImplementedError`.

- [ ] **Step 3: Implement `clear_active`**

Replace the `clear_active` stub in `plugins/_shared/session_key/session_key.py` with:

```python
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
    entries = raw.get("active_by_claude_pid") or {}
    entries.pop(key, None)
    new_data = {"schema_version": 2, "active_by_claude_pid": entries}
    _atomic_write(file, yaml.safe_dump(new_data, sort_keys=False))
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/test_session_key.py::TestClearActive -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the full shared test suite**

```bash
uv run pytest tests/test_session_key.py -v
```

Expected: all previously-written tests still pass (4 from Task 2 + 6 + 6 + 3 = 19).

- [ ] **Step 6: Commit**

```bash
git add plugins/_shared/session_key/session_key.py plugins/_shared/tests/test_session_key.py
git commit -m "feat(session_key/724): implement clear_active preserving other sessions"
```

---

## Task 6: Wire shared helper into proj `state.py`

**Files:**
- Modify: `plugins/proj/server/server/lib/state.py`
- Modify: `plugins/proj/server/tests/test_state.py`

Order of operations: refactor first, then add multi-session tests. The multi-session tests reference a `_session_key_fn` attribute that the refactor introduces, so writing them before the refactor would produce a collection-time error (not a useful TDD failure). Existing `TestSessionState` tests provide the safety net during the refactor — they must keep passing.

- [ ] **Step 1: Refactor `state.py` to delegate file I/O to the shared helper**

Replace the body of `plugins/proj/server/server/lib/state.py` with:

```python
"""Session-scoped state for proj MCP server.

Active project is session-scoped AND file-backed for cross-process visibility
(wiki plugin reads proj-session.yaml via wiki_scope_detect). In-memory state
takes priority per process; the on-disk file is pid-keyed so multiple concurrent
Claude Code sessions do not clobber each other. All file I/O is delegated to
the shared `session_key` helper.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

import session_key

_SESSION_FILE: Final[Path] = Path.home() / ".claude" / "proj-session.yaml"

# Wrapped so tests can monkey-patch without touching psutil internals.
_session_key_fn = session_key.get_claude_session_key

_session_active_project: str | None = None


def get_session_active() -> str | None:
    """Return the session-scoped active project.

    In-memory state wins; falls back to the pid-keyed on-disk session file
    (useful after MCP server restarts within the same Claude Code session).
    """
    if _session_active_project is not None:
        return _session_active_project
    return session_key.read_active(_SESSION_FILE, session_key=_session_key_fn())


def set_session_active(name: str) -> None:
    """Set the session-scoped active project. Writes to both in-memory + disk."""
    global _session_active_project
    _session_active_project = name
    session_key.write_active(_SESSION_FILE, name, session_key=_session_key_fn())


def clear_session_active() -> None:
    """Clear session-scoped active project from both in-memory + disk. Idempotent."""
    global _session_active_project
    _session_active_project = None
    session_key.clear_active(_SESSION_FILE, session_key=_session_key_fn())


def resolve_project(project_name: str | None) -> str | None:
    """Resolve which project to operate on.

    Resolution order: explicit project_name → session-scoped active → None.
    Tools should return 'No active project.' when this returns None.
    """
    return project_name or get_session_active()
```

- [ ] **Step 2: Run existing tests to verify the refactor didn't regress them**

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi/plugins/proj/server
uv run pytest tests/test_state.py -v
```

Expected: all existing `TestSessionState` tests pass. They use a single session_key per test (whatever `get_claude_session_key()` returns in the test process), so writes and reads stay consistent.

- [ ] **Step 3: Write failing tests for multi-session isolation**

Add a new test class at the bottom of `plugins/proj/server/tests/test_state.py`:

```python
class TestMultiSessionIsolation:
    def test_two_sessions_dont_clobber(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Writes from two distinct session_keys coexist in the file."""
        # Session 1 writes:
        monkeypatch.setattr(state, "_session_key_fn", lambda: "s1")
        set_session_active("proj-a")

        # Simulate a DIFFERENT Claude Code session sharing the same file:
        monkeypatch.setattr(state, "_session_key_fn", lambda: "s2")
        state._session_active_project = None  # fresh in-memory (different process)
        set_session_active("proj-b")

        # Session 1 view (fresh in-memory, reads disk):
        monkeypatch.setattr(state, "_session_key_fn", lambda: "s1")
        state._session_active_project = None
        assert get_session_active() == "proj-a"

        # Session 2 view:
        monkeypatch.setattr(state, "_session_key_fn", lambda: "s2")
        state._session_active_project = None
        assert get_session_active() == "proj-b"

    def test_clear_one_session_leaves_other_intact(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(state, "_session_key_fn", lambda: "s1")
        set_session_active("proj-a")
        monkeypatch.setattr(state, "_session_key_fn", lambda: "s2")
        state._session_active_project = None
        set_session_active("proj-b")

        monkeypatch.setattr(state, "_session_key_fn", lambda: "s1")
        state._session_active_project = None
        clear_session_active()

        # s2 still resolves:
        monkeypatch.setattr(state, "_session_key_fn", lambda: "s2")
        state._session_active_project = None
        assert get_session_active() == "proj-b"

    def test_read_migrates_v1_file(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A legacy v1 file → read() returns the scalar for the current session."""
        import yaml as _yaml
        state._SESSION_FILE.write_text(_yaml.safe_dump({"active": "legacy"}))

        monkeypatch.setattr(state, "_session_key_fn", lambda: "s1")
        state._session_active_project = None
        assert get_session_active() == "legacy"
```

- [ ] **Step 4: Run tests to verify the new tests pass**

```bash
uv run pytest tests/test_state.py::TestMultiSessionIsolation -v
```

Expected: 3 passed.

- [ ] **Step 5: Run the broader proj test suite**

```bash
uv run pytest -v --no-header
```

Expected: all pass. If any test outside `test_state.py` reads or writes `proj-session.yaml` directly with v1 shape, migrate it to write via `set_session_active` or the v2 shape.

- [ ] **Step 6: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi
git add plugins/proj/server/server/lib/state.py plugins/proj/server/tests/test_state.py
git commit -m "feat(proj/724): delegate proj-session.yaml R/W to session_key helper"
```

---

## Task 7: Wire shared helper into wiki `scope.py`

**Files:**
- Modify: `plugins/wiki/server/server/tools/scope.py`
- Modify: `plugins/wiki/server/tests/test_scope.py`
- Modify: `plugins/wiki/server/tests/conftest.py`

Order of operations mirrors Task 6: refactor first, then add multi-session tests. The new tests reference `scope._session_key_fn`, which the refactor introduces.

- [ ] **Step 1: Refactor `scope.py` to delegate to the shared helper**

Replace the body of `plugins/wiki/server/server/tools/scope.py` with:

```python
"""wiki_scope_detect: resolve active-project scope via proj plugin state.

Reads two files, both owned by proj plugin:
  - ~/.claude/proj.yaml          (existence signal → proj_present)
  - ~/.claude/proj-session.yaml  (pid-keyed v2 schema; active project for this session)

No cross-MCP calls; pure file I/O per spec §3 persistence/synthesis boundary.
The pid-key logic lives in the shared `session_key` helper (see plugins/_shared/session_key/).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import session_key

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_PROJ_YAML_PATH = Path.home() / ".claude" / "proj.yaml"
_SESSION_YAML_PATH = Path.home() / ".claude" / "proj-session.yaml"
_session_key_fn = session_key.get_claude_session_key


def register(mcp: FastMCP) -> None:
    mcp.tool()(wiki_scope_detect)


def _read_active_from_session() -> str | None:
    """Read active project for the current session from v2 proj-session.yaml."""
    return session_key.read_active(_SESSION_YAML_PATH, session_key=_session_key_fn())


def _proj_yaml_present() -> bool:
    """True if ~/.claude/proj.yaml exists (regardless of contents)."""
    return _PROJ_YAML_PATH.exists()


def wiki_scope_detect() -> str:
    """Detect active project scope via proj plugin's session file.

    Returns JSON {scope, proj_present}:
        - scope: "project:<name>" if this session has an active project, else "global"
        - proj_present: whether ~/.claude/proj.yaml exists on disk
    """
    proj_present = _proj_yaml_present()
    active = _read_active_from_session()
    scope = f"project:{active}" if active else "global"
    return json.dumps({"scope": scope, "proj_present": proj_present})
```

- [ ] **Step 2: Run existing tests to verify the refactor preserves v1 reads**

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi/plugins/wiki/server
uv run pytest tests/test_scope.py -v
```

Expected: all existing tests still pass. They write v1 shape (`{active: my-proj}`) which the shared helper handles via read-time migration.

- [ ] **Step 3: Add the `pin_wiki_session_key` fixture**

Add a helper fixture to `plugins/wiki/server/tests/conftest.py`, just above the `proj_paths` fixture:

```python
@pytest.fixture
def pin_wiki_session_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force scope.py's session_key lookup to return a deterministic value."""
    monkeypatch.setattr("server.tools.scope._session_key_fn", lambda: "wiki-test-sess")
```

- [ ] **Step 4: Write failing tests for wiki multi-session + v2 read**

Append to `plugins/wiki/server/tests/test_scope.py`:

```python
class TestWikiScopeMultiSession:
    @pytest.mark.asyncio
    async def test_v2_file_returns_own_session_active(
        self,
        mcp_app: FastMCP,
        proj_paths: dict[str, Path],
        pin_wiki_session_key: None,
    ) -> None:
        """wiki picks the entry matching its own session_key, not anyone else's."""
        proj_paths["proj_yaml"].write_text(yaml.safe_dump({}))
        proj_paths["session_yaml"].write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "active_by_claude_pid": {
                        "wiki-test-sess": {"active": "mine", "last_seen": "x"},
                        "other-sess": {"active": "theirs", "last_seen": "x"},
                    },
                }
            )
        )
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "project:mine"

    @pytest.mark.asyncio
    async def test_v2_file_unknown_session_returns_global(
        self,
        mcp_app: FastMCP,
        proj_paths: dict[str, Path],
        pin_wiki_session_key: None,
    ) -> None:
        """wiki session not in the file → global scope."""
        proj_paths["proj_yaml"].write_text(yaml.safe_dump({}))
        proj_paths["session_yaml"].write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "active_by_claude_pid": {
                        "other-sess": {"active": "theirs", "last_seen": "x"},
                    },
                }
            )
        )
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "global"

    @pytest.mark.asyncio
    async def test_v1_file_still_resolves_for_current_session(
        self,
        mcp_app: FastMCP,
        proj_paths: dict[str, Path],
        pin_wiki_session_key: None,
    ) -> None:
        """Backward-compat: v1 file → scope returns the scalar."""
        proj_paths["session_yaml"].write_text(yaml.safe_dump({"active": "legacy"}))
        result = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result["scope"] == "project:legacy"
```

- [ ] **Step 5: Run the full wiki scope test suite**

```bash
uv run pytest tests/test_scope.py -v
```

Expected: all pre-existing tests still pass + 3 new `TestWikiScopeMultiSession` tests pass.

Also run the cross-plugin e2e tests (which exercise scope with proj):

```bash
uv run pytest tests/test_e2e_integration.py tests/test_wiki_proj_e2e.py -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi
git add plugins/wiki/server/server/tools/scope.py plugins/wiki/server/tests/test_scope.py plugins/wiki/server/tests/conftest.py
git commit -m "feat(wiki/724): delegate proj-session.yaml read to session_key helper"
```

---

## Task 8: End-to-end multi-session simulation test

**Files:**
- Create: `plugins/wiki/server/tests/test_scope_multi_session_e2e.py`

- [ ] **Step 1: Write the integration test**

Create `plugins/wiki/server/tests/test_scope_multi_session_e2e.py`:

```python
"""End-to-end multi-session isolation test.

Simulates two Claude Code sessions writing via proj's state.set_session_active
and verifies each session's wiki_scope_detect reads back its own active project.
This is the canonical regression test for todo 724.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from mcp.server.fastmcp import FastMCP

from tests.conftest import call_tool


@pytest.mark.asyncio
class TestMultiSessionScopeE2E:
    async def test_two_sessions_isolated_via_pid_keys(
        self,
        mcp_app: FastMCP,
        proj_paths: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Simulate two sessions writing v2 entries; each sees only its own."""
        proj_paths["proj_yaml"].write_text(yaml.safe_dump({}))

        # Simulate session 1 writing its active project:
        proj_paths["session_yaml"].write_text(
            yaml.safe_dump(
                {
                    "schema_version": 2,
                    "active_by_claude_pid": {
                        "sess-1": {"active": "proj-one", "last_seen": "2026-04-24T10:00:00"},
                        "sess-2": {"active": "proj-two", "last_seen": "2026-04-24T10:00:00"},
                    },
                }
            )
        )

        # wiki running as session 1:
        monkeypatch.setattr("server.tools.scope._session_key_fn", lambda: "sess-1")
        result1 = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result1["scope"] == "project:proj-one"

        # wiki running as session 2 (same file, different session key):
        monkeypatch.setattr("server.tools.scope._session_key_fn", lambda: "sess-2")
        result2 = json.loads(await call_tool(mcp_app, "wiki_scope_detect"))
        assert result2["scope"] == "project:proj-two"
```

- [ ] **Step 2: Run the test**

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi/plugins/wiki/server
uv run pytest tests/test_scope_multi_session_e2e.py -v
```

Expected: 1 passed. This is the direct answer to todo 724's "Verify concern before designing fix" checklist.

- [ ] **Step 3: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi
git add plugins/wiki/server/tests/test_scope_multi_session_e2e.py
git commit -m "test(wiki/724): e2e multi-session scope isolation regression test"
```

---

## Task 9: Document v2 schema + env var

**Files:**
- Modify: `CLAUDE.md` (repo root)
- Modify: `plugins/wiki/server/server/tools/scope.py` (docstring already updated in Task 7 — verify)

- [ ] **Step 1: Update repo CLAUDE.md**

Open `/home/raul/worktrees/cpm/feat-724-proj-session-multi/CLAUDE.md`. In the "Wiki Plugin Config Flags" section (which describes `~/.claude/proj-session.yaml`), replace:

```markdown
**`~/.claude/proj-session.yaml`** (proj session state — owned by proj, read by wiki):
- `active: <project-name>` — session-scoped active project; wiki's `wiki_scope_detect` reads this to return `scope: project:<name>`. Cleared on `/proj:archive` or explicit clear.
```

with:

```markdown
**`~/.claude/proj-session.yaml`** (proj session state — owned by proj, read by wiki):
- Schema v2 — pid-keyed so concurrent Claude Code sessions don't clobber each other.
  ```yaml
  schema_version: 2
  active_by_claude_pid:
    "<claude-code-pid>":
      active: <project-name>
      last_seen: <iso8601>
  ```
- Each MCP subprocess resolves its slot by walking its ppid chain via `psutil`
  to find its Claude Code ancestor. Matcher regex configurable via env var
  `CPM_CLAUDE_CODE_CMDLINE_MATCHER` (default: `(?:^|/)claude(?:\s|$)`).
- Dead pid entries are garbage-collected on write. v1 files with a flat
  `active:` scalar auto-migrate into the current session's slot on first read.
- Cleared on `/proj:archive` (current session only) or explicit clear.
- Shared helper: `plugins/_shared/session_key/` (both proj and wiki import from here).
```

- [ ] **Step 2: Commit**

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi
git add CLAUDE.md
git commit -m "docs(724): document proj-session.yaml v2 schema + matcher env var"
```

---

## Task 10: Full cross-plugin test sweep

**Files:** none modified — verification only.

- [ ] **Step 1: Run shared + proj + wiki suites**

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi/plugins/_shared
uv run pytest -v
```

Expected: all pass, coverage ≥80% for `session_key`.

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi/plugins/proj/server
uv run pytest -v
```

Expected: all pass.

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi/plugins/wiki/server
uv run pytest -v
```

Expected: all pass.

- [ ] **Step 2: Run basedpyright + ruff on touched packages**

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi/plugins/_shared
uv run basedpyright session_key/
uv run ruff check session_key/ tests/test_session_key.py
```

Expected: no errors.

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi/plugins/proj/server
uv run basedpyright server/lib/state.py
uv run ruff check server/lib/state.py tests/test_state.py
```

Expected: no errors.

```bash
cd /home/raul/worktrees/cpm/feat-724-proj-session-multi/plugins/wiki/server
uv run basedpyright server/tools/scope.py
uv run ruff check server/tools/scope.py tests/test_scope.py tests/test_scope_multi_session_e2e.py
```

Expected: no errors.

- [ ] **Step 3: No commit — if any failures, return to the relevant task**

If tests/lint fail, fix inline within the task they belong to and commit separately. This step has no artifact; it's a gate before claiming the work is done.

---

## Self-Review Checklist (run after all tasks written, before handoff)

- **Spec coverage**: every spec §§ has a task.
  - Problem + verification → covered by Tasks 6, 7, 8 tests.
  - Scope signals → respected (pid-scoped, hook-compatible).
  - SessionStart hook compatibility → covered by Task 6 (set_session_active unchanged externally).
  - Chosen approach A details (schema v2, migration, GC, matcher env var) → Tasks 3, 4, 5, 9.
  - Open questions (matcher robustness, GC threshold, test injection, shared helper location) → addressed in plan (shared helper = `plugins/_shared/session_key/`; GC simplified to `pid_exists` only; test injection via `_session_key_fn` attr).
- **Placeholder scan**: no TBDs, no "add error handling", every code block is complete.
- **Type consistency**: `session_key.read_active`, `.write_active`, `.clear_active`, `.get_claude_session_key` used consistently across all tasks. `_session_key_fn` used identically in proj state.py and wiki scope.py.
- **Open question resolutions embedded**:
  - Matcher robustness — default regex `(?:^|/)claude(?:\s|$)` matches bare `claude` cmdline but NOT `uv run proj-server` (verified by Task 2 test). Env var override available.
  - GC threshold — simplified from 24h + pid_exists to `pid_exists` only (rationale: pid-reuse is self-correcting because any live session writes its own slot on startup).
  - Test injection — via `_session_key_fn` module attr in state.py and scope.py, monkey-patchable.
  - Shared helper location — `plugins/_shared/session_key/` (consistent with `hook_dispatch`, `scrubbing`, etc.).

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-24-proj-session-multi.md`. Two execution options:

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. Uses `superpowers:subagent-driven-development`.
2. **Inline Execution** — Execute tasks in this session using `superpowers:executing-plans`, batch execution with checkpoints.

Which approach?
