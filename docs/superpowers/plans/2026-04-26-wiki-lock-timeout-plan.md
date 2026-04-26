# Wiki Lock Timeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace blocking `fcntl.flock(LOCK_EX)` and `RLock.acquire()` in wiki_lock with timeout-bounded versions that raise `WikiLockTimeoutError` after 30s; wrap MCP tool callers to return JSON error on timeout.

**Architecture:** All edits in `plugins/wiki/server/server/lib/storage.py` (lock primitive, exception class, helpers) + 4 tool files (log.py, index.py, page.py, search.py) for the per-tool catch+JSON wrapper. New test module `tests/test_wiki_lock_timeout.py`. Reentrancy via `_HELD_LOCKS.fds` per-thread is preserved unchanged. No-contention acquire path stays at microsecond cost.

**Tech Stack:** Python 3.13, fcntl, threading, multiprocessing (for cross-process integration test), pytest, ruff, basedpyright.

**Spec:** `docs/superpowers/specs/2026-04-26-wiki-lock-timeout-design.md`.

---

## Files Touched

**Modify:**
- `plugins/wiki/server/server/lib/storage.py` — add `WikiLockTimeoutError`, constants, `_flock_with_timeout`, `_read_lock_holder_pid`; refactor `wiki_lock`.
- `plugins/wiki/server/server/tools/log.py` — wrap `wiki_log_append` (line 28).
- `plugins/wiki/server/server/tools/index.py` — wrap `wiki_index_rebuild` (line 45).
- `plugins/wiki/server/server/tools/page.py` — wrap `wiki_page_write` (line 44), `wiki_page_delete` (line 221).
- `plugins/wiki/server/server/tools/search.py` — wrap `wiki_search_bm25` (line 56), `wiki_search_index_refresh` (line 110).

**Create:**
- `plugins/wiki/server/tests/test_wiki_lock_timeout.py` — all timeout tests.

**Verified call-site list (audit complete):**
```
plugins/wiki/server/server/lib/bm25.py:119          # internal helper, called by search.py tools
plugins/wiki/server/server/lib/storage.py:103       # the with_wiki_lock decorator (no behavior change needed)
plugins/wiki/server/server/tools/log.py:40
plugins/wiki/server/server/tools/index.py:105
plugins/wiki/server/server/tools/page.py:91
plugins/wiki/server/server/tools/page.py:237
```

The `bm25.py:119` site is wrapped by virtue of its callers in `search.py` being wrapped; no direct change needed.

---

## Task 1: Add `WikiLockTimeoutError` exception class

**Files:**
- Modify: `plugins/wiki/server/server/lib/storage.py`
- Test: `plugins/wiki/server/tests/test_wiki_lock_timeout.py` (new)

- [ ] **Step 1: Create test module + write failing import test**

Create `plugins/wiki/server/tests/test_wiki_lock_timeout.py`:

```python
"""Tests for wiki_lock timeout + WikiLockTimeoutError."""

from __future__ import annotations

import pytest


class TestExceptionClass:
    def test_wiki_lock_timeout_error_importable(self) -> None:
        from server.lib.storage import WikiLockTimeoutError

        assert issubclass(WikiLockTimeoutError, Exception)

    def test_wiki_lock_timeout_error_message_preserved(self) -> None:
        from server.lib.storage import WikiLockTimeoutError

        err = WikiLockTimeoutError("test message")
        assert str(err) == "test message"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_timeout.py::TestExceptionClass -v`
Expected: FAIL — `ImportError: cannot import name 'WikiLockTimeoutError'`.

- [ ] **Step 3: Add the exception class to storage.py**

In `plugins/wiki/server/server/lib/storage.py`, add immediately after the imports block (around line 13, before `_WIKI_LOCK = threading.RLock()`):

```python
class WikiLockTimeoutError(Exception):
    """Raised when wiki_lock cannot acquire RLock or flock within budget."""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_timeout.py::TestExceptionClass -v`
Expected: PASS (2/2).

- [ ] **Step 5: Commit**

```bash
git add plugins/wiki/server/server/lib/storage.py plugins/wiki/server/tests/test_wiki_lock_timeout.py
git commit -m "feat(wiki/lock): WikiLockTimeoutError exception class"
```

---

## Task 2: Add timeout constants + `_flock_with_timeout` helper

**Files:**
- Modify: `plugins/wiki/server/server/lib/storage.py`
- Test: append to `plugins/wiki/server/tests/test_wiki_lock_timeout.py`

- [ ] **Step 1: Append failing tests for the helper**

Append to `plugins/wiki/server/tests/test_wiki_lock_timeout.py`:

```python
import os
import multiprocessing
import time
from pathlib import Path

from server.lib import storage
from server.lib.storage import (
    WIKI_LOCK_RETRY_INTERVAL,
    WIKI_LOCK_TIMEOUT,
    WikiLockTimeoutError,
    _flock_with_timeout,
)


@pytest.fixture
def fast_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lower the 30s production timeout to 0.5s for fast unit tests."""
    monkeypatch.setattr("server.lib.storage.WIKI_LOCK_TIMEOUT", 0.5)


def _hold_flock_then_sleep(lock_path: str, hold_seconds: float, ready_event_path: str) -> None:
    """Subprocess helper: open lock_path, take fcntl flock, signal ready, sleep, release."""
    import fcntl

    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    Path(ready_event_path).touch()  # signal that flock is held
    time.sleep(hold_seconds)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


class TestConstants:
    def test_default_constants(self) -> None:
        assert WIKI_LOCK_TIMEOUT == 30.0
        assert WIKI_LOCK_RETRY_INTERVAL == 0.1


class TestFlockWithTimeout:
    def test_acquires_immediately_when_uncontended(self, tmp_path: Path) -> None:
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        fd = os.open(str(lock_path), os.O_RDWR)
        try:
            start = time.monotonic()
            _flock_with_timeout(fd, lock_path)
            elapsed = time.monotonic() - start
            assert elapsed < 0.05
        finally:
            import fcntl
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_raises_on_timeout_with_holder_pid(
        self, tmp_path: Path, fast_timeout: None
    ) -> None:
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        ready = tmp_path / ".ready"
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(
            target=_hold_flock_then_sleep, args=(str(lock_path), 2.0, str(ready))
        )
        proc.start()
        try:
            # Wait for subprocess to acquire the lock
            for _ in range(50):
                if ready.exists():
                    break
                time.sleep(0.02)
            assert ready.exists(), "subprocess did not acquire flock in time"

            fd = os.open(str(lock_path), os.O_RDWR)
            try:
                with pytest.raises(WikiLockTimeoutError) as exc_info:
                    _flock_with_timeout(fd, lock_path)
                msg = str(exc_info.value)
                assert "flock" in msg
                # Holder pid is best-effort; assert it's the subprocess pid OR "unknown"
                assert (f"pid {proc.pid}" in msg) or ("unknown holder" in msg)
            finally:
                os.close(fd)
        finally:
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
                proc.join()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_timeout.py::TestConstants tests/test_wiki_lock_timeout.py::TestFlockWithTimeout -v`
Expected: FAIL — `ImportError: cannot import name 'WIKI_LOCK_TIMEOUT'` etc.

- [ ] **Step 3: Add constants + `_flock_with_timeout` to storage.py**

In `plugins/wiki/server/server/lib/storage.py`:

1. Add `import time` to the imports block (after `import threading` at line 8).
2. Just below the `WikiLockTimeoutError` class (added in Task 1), add:

```python
WIKI_LOCK_TIMEOUT = 30.0  # seconds; applies to both RLock and flock layers
WIKI_LOCK_RETRY_INTERVAL = 0.1  # seconds between flock LOCK_NB retry attempts


def _flock_with_timeout(fd: int, lock_path: Path) -> None:
    """Acquire fcntl flock(LOCK_EX) with a budget; raises WikiLockTimeoutError on expiry.

    Loops with LOCK_NB + sleep so the no-contention path stays microsecond-fast.
    Reads WIKI_LOCK_TIMEOUT at call time so monkeypatched values take effect.
    """
    deadline = time.monotonic() + WIKI_LOCK_TIMEOUT
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                holder = _read_lock_holder_pid(lock_path)
                holder_str = f"pid {holder}" if holder is not None else "unknown holder"
                raise WikiLockTimeoutError(
                    f"wiki lock fcntl flock not acquired within {WIKI_LOCK_TIMEOUT}s "
                    f"(held by {holder_str})"
                )
            time.sleep(WIKI_LOCK_RETRY_INTERVAL)
```

The `_read_lock_holder_pid` helper is added in Task 3 — for now this code references it. Tests in this task that check the holder-pid format will need Task 3 to land before they fully exercise the holder path, but `WikiLockTimeoutError` itself is raised regardless and the test asserts `"unknown holder"` as an acceptable fallback.

- [ ] **Step 4: Add stub `_read_lock_holder_pid` returning None**

To unblock Task 2 tests, add a temporary stub to storage.py (will be replaced in Task 3):

```python
def _read_lock_holder_pid(lock_path: Path) -> int | None:
    """Stub — replaced with real /proc/locks parser in Task 3."""
    return None
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_timeout.py::TestConstants tests/test_wiki_lock_timeout.py::TestFlockWithTimeout -v`
Expected: PASS. (Holder-pid test passes via the "unknown holder" branch since stub returns None.)

- [ ] **Step 6: Commit**

```bash
git add plugins/wiki/server/server/lib/storage.py plugins/wiki/server/tests/test_wiki_lock_timeout.py
git commit -m "feat(wiki/lock): _flock_with_timeout helper + constants"
```

---

## Task 3: Implement `_read_lock_holder_pid` (real /proc/locks parser)

**Files:**
- Modify: `plugins/wiki/server/server/lib/storage.py`
- Test: append to `plugins/wiki/server/tests/test_wiki_lock_timeout.py`

- [ ] **Step 1: Append failing tests for the helper**

Append to `plugins/wiki/server/tests/test_wiki_lock_timeout.py`:

```python
from server.lib.storage import _read_lock_holder_pid


class TestReadLockHolderPid:
    def test_returns_none_when_lock_unheld(self, tmp_path: Path) -> None:
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        assert _read_lock_holder_pid(lock_path) is None

    def test_handles_missing_proc_locks(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock_path = tmp_path / ".lock"
        lock_path.touch()

        # Force open("/proc/locks") to raise OSError
        original_open = open

        def fake_open(path: str, *args: object, **kwargs: object) -> object:
            if path == "/proc/locks":
                raise OSError("simulated /proc/locks unavailable")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", fake_open)
        assert _read_lock_holder_pid(lock_path) is None

    def test_handles_malformed_lines(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        lock_path = tmp_path / ".lock"
        lock_path.touch()

        from io import StringIO

        original_open = open

        def fake_open(path: str, *args: object, **kwargs: object) -> object:
            if path == "/proc/locks":
                return StringIO("garbage\nshort\nnot valid\n")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr("builtins.open", fake_open)
        assert _read_lock_holder_pid(lock_path) is None

    def test_returns_holder_pid_when_subprocess_holds_lock(
        self, tmp_path: Path
    ) -> None:
        """Integration test: subprocess holds flock; helper returns its pid."""
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        ready = tmp_path / ".ready"
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(
            target=_hold_flock_then_sleep, args=(str(lock_path), 2.0, str(ready))
        )
        proc.start()
        try:
            for _ in range(50):
                if ready.exists():
                    break
                time.sleep(0.02)
            assert ready.exists()

            holder = _read_lock_holder_pid(lock_path)
            # On Linux w/ /proc/locks accessible, this returns the subprocess pid.
            # On non-Linux or /proc/locks unavailable, returns None.
            assert holder is None or holder == proc.pid
        finally:
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
                proc.join()
```

- [ ] **Step 2: Run tests to verify the new ones fail (or skip on non-Linux)**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_timeout.py::TestReadLockHolderPid -v`
Expected: FAIL — `test_returns_holder_pid_when_subprocess_holds_lock` fails because the stub always returns None (not the pid). The other 3 tests pass with the stub.

- [ ] **Step 3: Replace the stub with the real implementation**

In `plugins/wiki/server/server/lib/storage.py`, replace the stub `_read_lock_holder_pid` from Task 2 with:

```python
def _read_lock_holder_pid(lock_path: Path) -> int | None:
    """Best-effort: parse /proc/locks for the pid holding flock on lock_path's inode.

    Returns None on non-Linux, /proc/locks unreadable, parse failure, or no match.
    Linux-only by design — degrades to None on other platforms.
    """
    try:
        target_inode = os.stat(lock_path).st_ino
    except OSError:
        return None
    try:
        with open("/proc/locks", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                # Format: "n: TYPE  KIND  MODE pid major:minor:inode start end"
                # Only FLOCK rows; skip POSIX rows.
                if len(parts) < 7 or parts[1] != "FLOCK":
                    continue
                pid_str = parts[4]
                inode_field = parts[5]  # "major:minor:inode"
                try:
                    inode = int(inode_field.rsplit(":", 1)[-1])
                except ValueError:
                    continue
                if inode == target_inode:
                    try:
                        return int(pid_str)
                    except ValueError:
                        return None
    except OSError:
        return None
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_timeout.py::TestReadLockHolderPid -v`
Expected: PASS (4/4 on Linux; integration test gracefully accepts None on non-Linux).

- [ ] **Step 5: Commit**

```bash
git add plugins/wiki/server/server/lib/storage.py plugins/wiki/server/tests/test_wiki_lock_timeout.py
git commit -m "feat(wiki/lock): _read_lock_holder_pid via /proc/locks"
```

---

## Task 4: Refactor `wiki_lock` context manager (RLock timeout + flock timeout integration)

**Files:**
- Modify: `plugins/wiki/server/server/lib/storage.py`
- Test: append to `plugins/wiki/server/tests/test_wiki_lock_timeout.py`

- [ ] **Step 1: Append failing tests for the refactored context manager**

Append to `plugins/wiki/server/tests/test_wiki_lock_timeout.py`:

```python
import threading

from server.lib.storage import _WIKI_LOCK, wiki_lock


class TestWikiLockContextManager:
    def test_no_contention_acquires_immediately(self, tmp_path: Path) -> None:
        start = time.monotonic()
        with wiki_lock(tmp_path):
            pass
        elapsed = time.monotonic() - start
        assert elapsed < 0.05

    def test_reentrant_same_thread(self, tmp_path: Path) -> None:
        with wiki_lock(tmp_path):
            with wiki_lock(tmp_path):
                pass

    def test_rlock_timeout_raises_with_layer_message(
        self, tmp_path: Path, fast_timeout: None
    ) -> None:
        # Hold the RLock from another thread for 1s, then release.
        # Main thread tries to acquire wiki_lock with fast_timeout=0.5s; should raise.
        held = threading.Event()
        release = threading.Event()

        def holder() -> None:
            _WIKI_LOCK.acquire()
            held.set()
            release.wait(timeout=2.0)
            _WIKI_LOCK.release()

        t = threading.Thread(target=holder)
        t.start()
        try:
            assert held.wait(timeout=1.0)
            with pytest.raises(WikiLockTimeoutError) as exc_info:
                with wiki_lock(tmp_path):
                    pass
            assert "RLock" in str(exc_info.value)
        finally:
            release.set()
            t.join(timeout=2.0)

    def test_rlock_released_after_flock_failure(
        self, tmp_path: Path, fast_timeout: None
    ) -> None:
        """If flock fails, RLock must be released so future acquires work."""
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        ready = tmp_path / ".ready"

        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(
            target=_hold_flock_then_sleep, args=(str(lock_path), 2.0, str(ready))
        )
        proc.start()
        try:
            for _ in range(50):
                if ready.exists():
                    break
                time.sleep(0.02)
            assert ready.exists()

            with pytest.raises(WikiLockTimeoutError):
                with wiki_lock(tmp_path):
                    pass

            # After the raise, _WIKI_LOCK must be released
            assert _WIKI_LOCK.acquire(timeout=0.1) is True
            _WIKI_LOCK.release()
        finally:
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
                proc.join()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_timeout.py::TestWikiLockContextManager -v`
Expected: FAIL — current `wiki_lock` blocks forever on RLock + flock contention; tests will hang or fail with timeout.

To avoid hanging: pytest's default test timeout will surface the issue. If no timeout configured, run with `--timeout=10` (install `pytest-timeout` if needed via `uv add --dev pytest-timeout`) — but per existing tests in the repo, pytest-anyio handles async timeouts; tests here are sync so manual interrupt may be needed. Skip this step's verification rigor: just confirm code change behavior in step 4.

- [ ] **Step 3: Refactor `wiki_lock` in storage.py**

Replace the entire `wiki_lock` function body (`storage.py:50-84`) with:

```python
@contextmanager
def wiki_lock(wiki_dir: Path) -> Generator[None, None, None]:
    """Acquire the shared wiki lock with a 30s timeout on each layer.

    Raises WikiLockTimeoutError if either the per-process RLock or the
    cross-process fcntl flock cannot be acquired within WIKI_LOCK_TIMEOUT
    seconds. Re-entrant within the same thread (existing behaviour preserved).
    """
    wiki_dir.mkdir(parents=True, exist_ok=True)
    lock_path = wiki_dir / _LOCK_FILENAME
    lock_path.touch(exist_ok=True)

    if not hasattr(_HELD_LOCKS, "fds"):
        _HELD_LOCKS.fds = cast("dict[str, int]", {})

    # Layer 1: per-process RLock (handles same-process other-thread contention).
    if not _WIKI_LOCK.acquire(timeout=WIKI_LOCK_TIMEOUT):
        raise WikiLockTimeoutError(
            f"wiki lock RLock not acquired within {WIKI_LOCK_TIMEOUT}s "
            "(another thread in this process holds it)"
        )
    try:
        fd: int | None = None
        fds = cast("dict[str, int]", _HELD_LOCKS.fds)
        is_first_acquire = str(wiki_dir) not in fds
        if is_first_acquire:
            fd = os.open(str(lock_path), os.O_RDWR)
            try:
                _flock_with_timeout(fd, lock_path)
            except Exception:
                os.close(fd)
                raise
            fds[str(wiki_dir)] = fd
        else:
            fd = fds[str(wiki_dir)]
        try:
            yield
        finally:
            if is_first_acquire and fd is not None:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
                del fds[str(wiki_dir)]
    finally:
        _WIKI_LOCK.release()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_timeout.py -v`
Expected: All tests in this module PASS (Tasks 1-4 combined).

- [ ] **Step 5: Run the full wiki test suite to check for regressions**

Run: `cd plugins/wiki/server && uv run pytest -v`
Expected: All existing tests pass (no regression). Coverage threshold met.

- [ ] **Step 6: Commit**

```bash
git add plugins/wiki/server/server/lib/storage.py plugins/wiki/server/tests/test_wiki_lock_timeout.py
git commit -m "refactor(wiki/lock): timeout-bounded wiki_lock context manager"
```

---

## Task 5: Wrap MCP tool callers (catch + return JSON error)

**Files:**
- Modify: `plugins/wiki/server/server/tools/log.py`
- Modify: `plugins/wiki/server/server/tools/index.py`
- Modify: `plugins/wiki/server/server/tools/page.py`
- Modify: `plugins/wiki/server/server/tools/search.py`
- Test: append to `plugins/wiki/server/tests/test_wiki_lock_timeout.py`

- [ ] **Step 1: Append failing tests for the tool wrappers**

Append to `plugins/wiki/server/tests/test_wiki_lock_timeout.py`:

```python
import json

from server.tools import log as log_tool
from server.tools import index as index_tool
from server.tools import page as page_tool
from server.tools import search as search_tool


class TestToolWrappers:
    """Each MCP tool must catch WikiLockTimeoutError and return JSON {error: 'lock_timeout'}."""

    @pytest.fixture
    def held_lock_subprocess(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Spawn a subprocess holding the wiki flock; configure wiki_dir to tmp_path."""
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        ready = tmp_path / ".ready"

        # Point all wiki tools at tmp_path
        from server.lib import config as config_mod
        from dataclasses import replace
        original_load = config_mod.load_config

        def fake_load_config():
            cfg = original_load()
            return replace(cfg, wiki_dir=tmp_path)

        monkeypatch.setattr("server.lib.config.load_config", fake_load_config)

        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(
            target=_hold_flock_then_sleep, args=(str(lock_path), 5.0, str(ready))
        )
        proc.start()
        for _ in range(50):
            if ready.exists():
                break
            time.sleep(0.02)
        assert ready.exists()
        yield
        proc.terminate()
        proc.join(timeout=5)

    def test_wiki_log_append_returns_lock_timeout_json(
        self, fast_timeout: None, held_lock_subprocess: None
    ) -> None:
        result = json.loads(log_tool.wiki_log_append(action="test", title="t"))
        assert result == {"error": "lock_timeout", "detail": pytest.approx_str_contains("flock")}

    def test_wiki_index_rebuild_returns_lock_timeout_json(
        self, fast_timeout: None, held_lock_subprocess: None
    ) -> None:
        result = json.loads(index_tool.wiki_index_rebuild())
        assert result["error"] == "lock_timeout"
        assert "flock" in result["detail"]

    def test_wiki_page_write_returns_lock_timeout_json(
        self, fast_timeout: None, held_lock_subprocess: None
    ) -> None:
        result = json.loads(
            page_tool.wiki_page_write(
                slug="x",
                category=None,
                frontmatter={
                    "title": "x",
                    "tags": [],
                    "links_to": [],
                    "scope": [],
                    "sources": [],
                    "last_ingested": "2026-04-26",
                },
                body="body",
            )
        )
        assert result["error"] == "lock_timeout"
        assert "flock" in result["detail"]

    def test_wiki_page_delete_returns_lock_timeout_json(
        self, tmp_path: Path, fast_timeout: None, held_lock_subprocess: None
    ) -> None:
        # Create a target page so wiki_page_delete reaches the lock acquisition
        pages_dir = tmp_path / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        (pages_dir / "x.md").write_text("---\ntitle: x\n---\nbody\n")
        result = json.loads(page_tool.wiki_page_delete(slug="x", category=None))
        assert result["error"] == "lock_timeout"
        assert "flock" in result["detail"]

    def test_wiki_search_index_refresh_returns_lock_timeout_json(
        self, fast_timeout: None, held_lock_subprocess: None
    ) -> None:
        result = json.loads(search_tool.wiki_search_index_refresh())
        assert result["error"] == "lock_timeout"
        assert "flock" in result["detail"]

    def test_wiki_search_bm25_returns_lock_timeout_json(
        self, fast_timeout: None, held_lock_subprocess: None
    ) -> None:
        result = json.loads(search_tool.wiki_search_bm25(query="test"))
        assert result["error"] == "lock_timeout"
        assert "flock" in result["detail"]
```

Note on `pytest.approx_str_contains` — this isn't a built-in helper. Replace lines using it with `assert "flock" in result["detail"]` style assertions (already used in other tests above). Adjust the first test (`test_wiki_log_append_returns_lock_timeout_json`) to match the same style:
```python
result = json.loads(log_tool.wiki_log_append(action="test", title="t"))
assert result["error"] == "lock_timeout"
assert "flock" in result["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_timeout.py::TestToolWrappers -v`
Expected: FAIL — tools currently let `WikiLockTimeoutError` propagate to the test as exception, not catch + return JSON.

- [ ] **Step 3: Wrap `wiki_log_append` in tools/log.py**

In `plugins/wiki/server/server/tools/log.py`, modify `wiki_log_append` (line 28) to wrap the body in try/except. Add import at top:

```python
from server.lib.storage import WikiLockTimeoutError
```

Replace the function body (line 28 onwards) with:

```python
def wiki_log_append(action: str, title: str, body: str = "") -> str:
    """Append an entry to log.md.

    Format: `## [YYYY-MM-DD] <action> | <title>` followed by optional body + blank line.
    """
    try:
        cfg = config_mod.load_config()
        wiki_dir = cfg.wiki_dir
        log_path = wiki_dir / LOG_FILENAME
        today = date.today().isoformat()
        header = f"## [{today}] {action} | {title}\n"
        entry = header + (body + "\n" if body else "") + "\n"

        with storage.wiki_lock(wiki_dir):
            wiki_dir.mkdir(parents=True, exist_ok=True)
            existing = log_path.read_text() if log_path.exists() else ""
            storage.atomic_write(log_path, existing + entry)

        return json.dumps({"entry": entry.strip(), "path": str(log_path)})
    except WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})
```

- [ ] **Step 4: Wrap `wiki_index_rebuild` in tools/index.py**

In `plugins/wiki/server/server/tools/index.py`:

1. Add at top: `from server.lib.storage import WikiLockTimeoutError`.
2. Wrap the body of `wiki_index_rebuild` in try/except. Find the function (line 45) and wrap the entire existing body in `try: ... except WikiLockTimeoutError as exc: return json.dumps({"error": "lock_timeout", "detail": str(exc)})`.

- [ ] **Step 5: Wrap `wiki_page_write` and `wiki_page_delete` in tools/page.py**

In `plugins/wiki/server/server/tools/page.py`:

1. Add at top: `from server.lib.storage import WikiLockTimeoutError`.
2. Wrap `wiki_page_write` (line 44) body in try/except returning the lock_timeout JSON.
3. Wrap `wiki_page_delete` (line 221) body in try/except returning the lock_timeout JSON.

For each: keep existing return statements unchanged inside the `try`; add the `except WikiLockTimeoutError as exc: return json.dumps({"error": "lock_timeout", "detail": str(exc)})` at the end.

- [ ] **Step 6: Wrap `wiki_search_bm25` and `wiki_search_index_refresh` in tools/search.py**

In `plugins/wiki/server/server/tools/search.py`:

1. Add at top: `from server.lib.storage import WikiLockTimeoutError`.
2. Wrap both function bodies in try/except returning the lock_timeout JSON.

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_timeout.py::TestToolWrappers -v`
Expected: PASS (6/6).

- [ ] **Step 8: Commit**

```bash
git add plugins/wiki/server/server/tools/log.py plugins/wiki/server/server/tools/index.py plugins/wiki/server/server/tools/page.py plugins/wiki/server/server/tools/search.py plugins/wiki/server/tests/test_wiki_lock_timeout.py
git commit -m "feat(wiki/tools): catch WikiLockTimeoutError + return JSON error"
```

---

## Task 6: Cross-process integration test

**Files:**
- Test: append to `plugins/wiki/server/tests/test_wiki_lock_timeout.py`

- [ ] **Step 1: Add the cross-process integration test**

Append to `plugins/wiki/server/tests/test_wiki_lock_timeout.py`:

```python
def _try_acquire_wiki_lock(
    wiki_dir: str, timeout: float, result_path: str
) -> None:
    """Subprocess helper: try to acquire wiki_lock, write outcome to result_path."""
    import json as _json
    from pathlib import Path as _Path

    # Lower the timeout in this subprocess too
    from server.lib import storage as _storage
    _storage.WIKI_LOCK_TIMEOUT = timeout

    try:
        with _storage.wiki_lock(_Path(wiki_dir)):
            _Path(result_path).write_text(_json.dumps({"acquired": True}))
    except _storage.WikiLockTimeoutError as exc:
        _Path(result_path).write_text(
            _json.dumps({"acquired": False, "error": str(exc)})
        )


class TestCrossProcessIntegration:
    def test_two_subprocesses_one_times_out(self, tmp_path: Path) -> None:
        """Process A holds wiki_lock for 1s; Process B times out at 0.5s."""
        ctx = multiprocessing.get_context("spawn")

        # Process A: hold the lock for 1 second
        a_result = tmp_path / "a.json"

        def hold_lock_for_one_second(wiki_dir: str, result_path: str) -> None:
            from pathlib import Path as _Path
            from server.lib import storage as _storage

            with _storage.wiki_lock(_Path(wiki_dir)):
                _Path(result_path).write_text("acquired")
                time.sleep(1.0)

        proc_a = ctx.Process(
            target=hold_lock_for_one_second, args=(str(tmp_path), str(a_result))
        )
        proc_a.start()

        # Wait for A to acquire
        for _ in range(50):
            if a_result.exists():
                break
            time.sleep(0.02)
        assert a_result.exists()

        # Process B: try to acquire with 0.5s timeout, should fail
        b_result = tmp_path / "b.json"
        proc_b = ctx.Process(
            target=_try_acquire_wiki_lock, args=(str(tmp_path), 0.5, str(b_result))
        )
        proc_b.start()
        proc_b.join(timeout=2.0)
        proc_a.join(timeout=2.0)

        assert b_result.exists()
        b_outcome = json.loads(b_result.read_text())
        assert b_outcome["acquired"] is False
        assert "flock" in b_outcome["error"]
```

- [ ] **Step 2: Run the integration test**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_timeout.py::TestCrossProcessIntegration -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add plugins/wiki/server/tests/test_wiki_lock_timeout.py
git commit -m "test(wiki/lock): cross-process integration test for timeout"
```

---

## Task 7: Final verification

- [ ] **Step 1: Run the full wiki test suite**

Run: `cd plugins/wiki/server && uv run pytest -v`
Expected: ALL pass; coverage ≥ 85%.

- [ ] **Step 2: Run lint + type check on touched files**

Run:
```bash
cd plugins/wiki/server && uv run ruff check . && uv run ruff format --check .
uv run basedpyright server/lib/storage.py server/tools/log.py server/tools/index.py server/tools/page.py server/tools/search.py tests/test_wiki_lock_timeout.py
```
Expected: clean.

- [ ] **Step 3: Commit any formatting fixes**

If ruff/basedpyright surfaced fixes:
```bash
git add -u
git commit -m "style: ruff/basedpyright fixes for wiki_lock timeout"
```

---

## Acceptance criteria recap

1. Two concurrent processes calling `wiki_lock(tmp_path)`: first holds for 1 s, second times out at 0.5 s (with `fast_timeout`) raising `WikiLockTimeoutError` containing `"flock"` and (when `/proc/locks` is available) the holder pid. **Covered by Task 6 + Task 4 step 1**.
2. No-contention `wiki_lock(...)` acquire returns within 100 ms (no observable overhead vs the original blocking implementation). **Covered by Task 4 `test_no_contention_acquires_immediately`**.
3. Reentrant `with wiki_lock(...)` calls within the same thread continue to work without re-acquiring the fd. **Covered by Task 4 `test_reentrant_same_thread`**.
4. After `WikiLockTimeoutError` is raised, the per-process `_WIKI_LOCK` RLock is released and an open fd is not leaked. **Covered by Task 4 `test_rlock_released_after_flock_failure`**.
5. Each affected MCP tool returns `{"error": "lock_timeout", "detail": "..."}` JSON instead of propagating `WikiLockTimeoutError` to the MCP transport layer. **Covered by Task 5 (6 tool tests)**.
6. All new + existing tests in `plugins/wiki/server/tests/` pass; coverage threshold (85%) maintained. **Covered by Task 7 step 1**.
