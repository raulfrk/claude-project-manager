# Wiki Async W1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert wiki plugin to async tools + anyio.Lock + LOCK_NB-with-timeout flock so concurrent fastmcp tasks no longer break mutual exclusion AND CPU-bound work no longer stalls the event loop. Wiki-only blast radius (no `_shared/` changes).

**Architecture:** Replace `wiki_lock` (was `threading.RLock` + `threading.local` fd cache, broken under same-thread anyio tasks) with an async context manager using `anyio.Lock` for in-process exclusion + `fcntl.flock` (LOCK_NB + 30s retry) on a worker thread for cross-process exclusion. Convert ~19 wiki MCP tool fns to `async def`, push their CPU/IO-bound bodies to worker threads via `await anyio.to_thread.run_sync(_helper, *args)`. `dispatch.py` and other 6 plugins UNCHANGED.

**Tech Stack:** Python 3.13, anyio (already a transitive dep via fastmcp), fcntl, multiprocessing (cross-process tests), pytest + pytest-anyio, ruff, basedpyright.

**Spec:** `docs/superpowers/specs/2026-04-26-wiki-async-w1-design.md`.

---

## Files Touched

**Modify** (wiki plugin only):
- `plugins/wiki/server/server/lib/storage.py` — anyio.Lock, exception classes, `_flock_with_timeout`, async `wiki_lock`. Delete `_WIKI_LOCK = threading.RLock()`, `_HELD_LOCKS = threading.local()`, `with_wiki_lock` decorator.
- `plugins/wiki/server/server/lib/bm25.py` — drop internal `with wiki_lock` from `rebuild_index` (caller's responsibility now).
- `plugins/wiki/server/server/tools/log.py` — `wiki_log_append`, `wiki_log_read` async.
- `plugins/wiki/server/server/tools/index.py` — `wiki_index_rebuild`, `wiki_index_read` async.
- `plugins/wiki/server/server/tools/page.py` — `wiki_page_write`, `wiki_page_get`, `wiki_page_list`, `wiki_page_delete` async.
- `plugins/wiki/server/server/tools/search.py` — `wiki_search_bm25`, `wiki_search_index_refresh` async + lock acquisition restructured to wrap bm25 calls.
- `plugins/wiki/server/server/tools/links.py` — `wiki_link_resolve` async (read-only, signature change only).
- `plugins/wiki/server/server/tools/lint.py` — 7 fns (`wiki_lint_orphans`, `wiki_lint_broken_links`, `wiki_lint_broken_section_refs`, `wiki_lint_category_violations`, `wiki_lint_stale`, `wiki_lint_schema`, `wiki_lint_duplicates`) async (read-only, signature change only).
- `plugins/wiki/server/server/tools/scope.py` — `wiki_scope_detect` async (read-only).
- Existing tests in `plugins/wiki/server/tests/` — every test that exercises a wiki tool needs `pytest.mark.anyio()` + `await`.

**Create**:
- `plugins/wiki/server/tests/test_wiki_lock_w1.py` — new test module covering mutex correctness, reentry, cross-process, timeout, event-loop responsiveness, tool wrappers.

**NOT affected**:
- `plugins/_shared/hook_dispatch/dispatch.py` — UNCHANGED.
- All other 6 plugins — UNCHANGED.

**Inventory verified** (`grep '^def wiki_'`):
- index.py: 2 fns. links.py: 1 fn. lint.py: 7 fns. log.py: 2 fns. page.py: 4 fns. scope.py: 1 fn. search.py: 2 fns. **Total: 19 public tool fns** matching the spec's "~20" estimate.

---

## Task 1: Add exception classes + constants to storage.py

**Files:**
- Modify: `plugins/wiki/server/server/lib/storage.py`
- Test: `plugins/wiki/server/tests/test_wiki_lock_w1.py` (new)

- [ ] **Step 1: Create test module + write failing import test**

Create `plugins/wiki/server/tests/test_wiki_lock_w1.py`:

```python
"""Tests for wiki_lock W1 fix: anyio.Lock + LOCK_NB + WikiLockTimeoutError."""

from __future__ import annotations

import pytest


class TestExceptionClasses:
    def test_wiki_lock_timeout_error_importable(self) -> None:
        from server.lib.storage import WikiLockTimeoutError

        assert issubclass(WikiLockTimeoutError, RuntimeError)

    def test_wiki_lock_reentry_error_importable(self) -> None:
        from server.lib.storage import WikiLockReentryError

        assert issubclass(WikiLockReentryError, RuntimeError)

    def test_constants_default(self) -> None:
        from server.lib.storage import WIKI_LOCK_RETRY_INTERVAL, WIKI_LOCK_TIMEOUT

        assert WIKI_LOCK_TIMEOUT == 30.0
        assert WIKI_LOCK_RETRY_INTERVAL == 0.1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_w1.py::TestExceptionClasses -v`
Expected: FAIL — `ImportError: cannot import name 'WikiLockTimeoutError'`.

- [ ] **Step 3: Add exception classes + constants to storage.py**

In `plugins/wiki/server/server/lib/storage.py`, add to the imports + after existing imports (after `from typing import ...`):

```python
import anyio
import time

# Existing imports remain. Add `import anyio` and `import time` if not present.

WIKI_LOCK_TIMEOUT = 30.0  # seconds; cross-process flock acquisition budget
WIKI_LOCK_RETRY_INTERVAL = 0.1  # seconds between flock LOCK_NB retry attempts


class WikiLockReentryError(RuntimeError):
    """Raised when wiki_lock detects same-task reentry (anyio.Lock is non-reentrant)."""


class WikiLockTimeoutError(RuntimeError):
    """Raised when cross-process flock cannot be acquired within WIKI_LOCK_TIMEOUT."""
```

Place these after the existing imports block and before `_WIKI_LOCK = threading.RLock()` (which will be replaced in Task 3).

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_w1.py::TestExceptionClasses -v`
Expected: PASS (3/3).

- [ ] **Step 5: Commit**

```bash
git add plugins/wiki/server/server/lib/storage.py plugins/wiki/server/tests/test_wiki_lock_w1.py
git commit -m "feat(wiki/lock): exception classes + constants for W1 fix"
```

---

## Task 2: Add `_flock_with_timeout` helper

**Files:**
- Modify: `plugins/wiki/server/server/lib/storage.py`
- Test: append to `plugins/wiki/server/tests/test_wiki_lock_w1.py`

- [ ] **Step 1: Append failing tests for the helper**

Append to `plugins/wiki/server/tests/test_wiki_lock_w1.py`:

```python
import fcntl
import multiprocessing
import os
import time
from pathlib import Path

from server.lib.storage import WikiLockTimeoutError, _flock_with_timeout


@pytest.fixture
def fast_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lower the 30s production timeout to 0.5s for fast unit tests."""
    monkeypatch.setattr("server.lib.storage.WIKI_LOCK_TIMEOUT", 0.5)


def _hold_flock_subprocess(lock_path: str, hold_s: float, ready_path: str) -> None:
    """Subprocess helper: open lock_path, take fcntl flock, signal ready, sleep, release."""
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    Path(ready_path).touch()
    time.sleep(hold_s)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


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
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def test_raises_timeout_when_subprocess_holds(
        self, tmp_path: Path, fast_timeout: None
    ) -> None:
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        ready = tmp_path / ".ready"
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(
            target=_hold_flock_subprocess, args=(str(lock_path), 2.0, str(ready))
        )
        proc.start()
        try:
            for _ in range(50):
                if ready.exists():
                    break
                time.sleep(0.02)
            assert ready.exists()

            fd = os.open(str(lock_path), os.O_RDWR)
            try:
                with pytest.raises(WikiLockTimeoutError, match="not acquired within"):
                    _flock_with_timeout(fd, lock_path)
            finally:
                os.close(fd)
        finally:
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
                proc.join()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_w1.py::TestFlockWithTimeout -v`
Expected: FAIL — `ImportError: cannot import name '_flock_with_timeout'`.

- [ ] **Step 3: Add `_flock_with_timeout` to storage.py**

Add to `plugins/wiki/server/server/lib/storage.py`, after the exception classes from Task 1:

```python
def _flock_with_timeout(fd: int, lock_path: Path) -> None:
    """Acquire fcntl.flock(LOCK_EX) with WIKI_LOCK_TIMEOUT budget.

    LOCK_NB retry loop with WIKI_LOCK_RETRY_INTERVAL between attempts.
    Reads WIKI_LOCK_TIMEOUT at call time so monkeypatched values take effect.

    Designed to run on a worker thread (called via anyio.to_thread.run_sync).
    The retry-loop sleep blocks the worker thread, not the event loop.

    Raises:
        WikiLockTimeoutError: if budget exhausted.
    """
    deadline = time.monotonic() + WIKI_LOCK_TIMEOUT
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise WikiLockTimeoutError(
                    f"wiki .lock not acquired within {WIKI_LOCK_TIMEOUT}s "
                    f"({lock_path}; another session/process likely holds it)"
                )
            time.sleep(WIKI_LOCK_RETRY_INTERVAL)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_w1.py::TestFlockWithTimeout -v`
Expected: PASS (2/2).

- [ ] **Step 5: Commit**

```bash
git add plugins/wiki/server/server/lib/storage.py plugins/wiki/server/tests/test_wiki_lock_w1.py
git commit -m "feat(wiki/lock): _flock_with_timeout helper (LOCK_NB + 30s retry)"
```

---

## Task 3: Refactor `wiki_lock` to async context manager

**Files:**
- Modify: `plugins/wiki/server/server/lib/storage.py`
- Test: append to `plugins/wiki/server/tests/test_wiki_lock_w1.py`

- [ ] **Step 1: Append failing tests for the async context manager**

Append to `plugins/wiki/server/tests/test_wiki_lock_w1.py`:

```python
import anyio

from server.lib.storage import WikiLockReentryError, wiki_lock


class TestWikiLockAsync:
    @pytest.mark.anyio()
    async def test_no_contention_acquires_immediately(self, tmp_path: Path) -> None:
        start = time.monotonic()
        async with wiki_lock(tmp_path):
            pass
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    @pytest.mark.anyio()
    async def test_two_tasks_serialize(self, tmp_path: Path) -> None:
        log: list[str] = []

        async def hold(name: str, hold_seconds: float) -> None:
            log.append(f"{name} REQUEST {time.monotonic():.3f}")
            async with wiki_lock(tmp_path):
                log.append(f"{name} ENTER {time.monotonic():.3f}")
                await anyio.sleep(hold_seconds)
                log.append(f"{name} EXIT {time.monotonic():.3f}")

        async with anyio.create_task_group() as tg:
            tg.start_soon(hold, "A", 0.5)
            await anyio.sleep(0.05)
            tg.start_soon(hold, "B", 0.5)

        a_enter = next(i for i, x in enumerate(log) if x.startswith("A ENTER"))
        a_exit = next(i for i, x in enumerate(log) if x.startswith("A EXIT"))
        b_enter = next(i for i, x in enumerate(log) if x.startswith("B ENTER"))
        assert a_enter < a_exit < b_enter, f"B entered before A exited: {log}"

    @pytest.mark.anyio()
    async def test_reentry_raises(self, tmp_path: Path) -> None:
        async with wiki_lock(tmp_path):
            with pytest.raises(WikiLockReentryError, match="nested wiki_lock"):
                async with wiki_lock(tmp_path):
                    pass

    @pytest.mark.anyio()
    async def test_cross_process_blocks_until_released(self, tmp_path: Path) -> None:
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        ready = tmp_path / ".ready"
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(
            target=_hold_flock_subprocess, args=(str(lock_path), 1.0, str(ready))
        )
        proc.start()
        try:
            for _ in range(50):
                if ready.exists():
                    break
                await anyio.sleep(0.02)
            assert ready.exists()

            start = time.monotonic()
            async with wiki_lock(tmp_path):
                elapsed = time.monotonic() - start
                assert elapsed > 0.5, f"acquired too fast: {elapsed}"
        finally:
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()
                proc.join()

    @pytest.mark.anyio()
    async def test_cross_process_timeout_raises(
        self, tmp_path: Path, fast_timeout: None
    ) -> None:
        lock_path = tmp_path / ".lock"
        lock_path.touch()
        ready = tmp_path / ".ready"
        ctx = multiprocessing.get_context("spawn")
        proc = ctx.Process(
            target=_hold_flock_subprocess, args=(str(lock_path), 2.0, str(ready))
        )
        proc.start()
        try:
            for _ in range(50):
                if ready.exists():
                    break
                await anyio.sleep(0.02)
            assert ready.exists()

            with pytest.raises(WikiLockTimeoutError, match="not acquired within"):
                async with wiki_lock(tmp_path):
                    pass
        finally:
            proc.join(timeout=5)
            if proc.is_alive():
                proc.terminate()
                proc.join()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_w1.py::TestWikiLockAsync -v`
Expected: FAIL — current `wiki_lock` is a sync context manager (uses `with` not `async with`).

- [ ] **Step 3: Refactor `wiki_lock` in storage.py**

In `plugins/wiki/server/server/lib/storage.py`:

1. Replace the line `_WIKI_LOCK = threading.RLock()  # re-entrant so same-thread nested wiki_lock() is fine` with:

```python
_WIKI_LOCK = anyio.Lock()  # in-process exclusion (anyio-aware, single per MCP process)
```

2. Delete the line `_HELD_LOCKS = threading.local()`.

3. Replace the entire `wiki_lock` function (currently lines ~50-84) with:

```python
@asynccontextmanager
async def wiki_lock(wiki_dir: Path) -> "AsyncGenerator[None, None]":
    """Acquire shared wiki lock: in-process anyio.Lock + cross-process fcntl.flock.

    Async context manager. Callers must use `async with wiki_lock(wiki_dir): ...`.

    Raises:
        WikiLockReentryError: if the calling task already holds the lock.
        WikiLockTimeoutError: if the cross-process flock cannot be acquired
            within WIKI_LOCK_TIMEOUT seconds.
    """
    if _WIKI_LOCK.statistics().owner is anyio.get_current_task():
        raise WikiLockReentryError(
            "nested wiki_lock detected (anyio.Lock is non-reentrant; "
            "refactor caller to acquire lock once at the outermost level)"
        )
    wiki_dir.mkdir(parents=True, exist_ok=True)
    lock_path = wiki_dir / _LOCK_FILENAME
    lock_path.touch(exist_ok=True)

    async with _WIKI_LOCK:
        fd = await anyio.to_thread.run_sync(os.open, str(lock_path), os.O_RDWR)
        try:
            await anyio.to_thread.run_sync(_flock_with_timeout, fd, lock_path)
            yield
        finally:
            with suppress(OSError):
                await anyio.to_thread.run_sync(fcntl.flock, fd, fcntl.LOCK_UN)
            await anyio.to_thread.run_sync(os.close, fd)
```

4. Update the imports section at the top of `storage.py`:
   - Replace `from contextlib import contextmanager, suppress` with `from contextlib import asynccontextmanager, suppress`.
   - In the `if TYPE_CHECKING:` block, change `from collections.abc import Callable, Generator` to `from collections.abc import AsyncGenerator, Callable`.
   - Remove the `import threading` line (no longer needed after deleting `_WIKI_LOCK = threading.RLock()` and `_HELD_LOCKS = threading.local()`).

5. Delete the entire `with_wiki_lock` decorator + supporting code (currently lines ~87-106 — the `P = ParamSpec("P")`, `R = TypeVar("R")`, and `def with_wiki_lock` block).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_w1.py::TestWikiLockAsync -v`
Expected: PASS (5/5).

- [ ] **Step 5: Commit**

```bash
git add plugins/wiki/server/server/lib/storage.py plugins/wiki/server/tests/test_wiki_lock_w1.py
git commit -m "refactor(wiki/lock): wiki_lock async context manager w/ anyio.Lock + LOCK_NB flock"
```

---

## Task 4: Move `wiki_lock` acquisition out of `bm25.py`

**Files:**
- Modify: `plugins/wiki/server/server/lib/bm25.py`

- [ ] **Step 1: Verify current `bm25.py:119` usage**

Run: `grep -n 'wiki_lock\|with storage' /home/raul/projects/claude-project-manager/plugins/wiki/server/server/lib/bm25.py`
Expected: shows the existing `with storage.wiki_lock(wiki_dir):` block in `rebuild_index`.

- [ ] **Step 2: Edit `rebuild_index` in `bm25.py`**

Find the function `rebuild_index` (around line 110-125). Currently it has:

```python
def rebuild_index(wiki_dir: Path) -> BM25Index:
    """..."""
    idx_dir = wiki_dir / ".index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    docs = _collect_page_tokens(wiki_dir)
    snapshot = _pages_latest_mtime(wiki_dir)
    data: dict[str, Any] = {
        "version": _SCHEMA_VERSION,
        "mtime_snapshot": snapshot,
        "docs": docs,
    }
    sidecar = sidecar_path(wiki_dir)
    with storage.wiki_lock(wiki_dir):
        storage.atomic_write(sidecar, json.dumps(data, separators=(",", ":")))

    idx = BM25Index(docs=docs)
    idx.build()
    return idx
```

Replace with:

```python
def rebuild_index(wiki_dir: Path) -> BM25Index:
    """Rebuild the BM25 sidecar index.

    NOTE: Caller MUST hold wiki_lock around invocation. This helper does NOT
    acquire the lock itself (changed in W1 fix 2026-04-26 — see todo 764).
    """
    idx_dir = wiki_dir / ".index"
    idx_dir.mkdir(parents=True, exist_ok=True)
    docs = _collect_page_tokens(wiki_dir)
    snapshot = _pages_latest_mtime(wiki_dir)
    data: dict[str, Any] = {
        "version": _SCHEMA_VERSION,
        "mtime_snapshot": snapshot,
        "docs": docs,
    }
    sidecar = sidecar_path(wiki_dir)
    storage.atomic_write(sidecar, json.dumps(data, separators=(",", ":")))

    idx = BM25Index(docs=docs)
    idx.build()
    return idx
```

The `import` at the top still needs `from server.lib import storage` (for `atomic_write` + `sidecar_path`); no other changes.

- [ ] **Step 3: Verify `load_or_rebuild` still works**

Read `bm25.py` around `load_or_rebuild`. If it calls `rebuild_index` directly without holding wiki_lock, that's now a bug. Add a comment or assertion that callers must hold the lock. (Inspection only — actual lock-acquisition by caller comes in Task 8.)

- [ ] **Step 4: Commit**

```bash
git add plugins/wiki/server/server/lib/bm25.py
git commit -m "refactor(wiki/bm25): drop internal wiki_lock; caller's responsibility now"
```

---

## Task 5: Convert `tools/log.py` to async

**Files:**
- Modify: `plugins/wiki/server/server/tools/log.py`
- Test: append to `plugins/wiki/server/tests/test_wiki_lock_w1.py`

- [ ] **Step 1: Append failing test**

Append to `plugins/wiki/server/tests/test_wiki_lock_w1.py`:

```python
import json

from server.tools.log import wiki_log_append, wiki_log_read


class TestLogToolsAsync:
    @pytest.mark.anyio()
    async def test_wiki_log_append_returns_str(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # Point config to tmp_path
        from dataclasses import replace
        from server.lib import config as config_mod
        original = config_mod.load_config

        def fake_load_config():
            cfg = original()
            return replace(cfg, wiki_dir=tmp_path)

        monkeypatch.setattr("server.lib.config.load_config", fake_load_config)

        result = json.loads(await wiki_log_append(action="test", title="my entry", body="hello"))
        assert "entry" in result
        assert "my entry" in result["entry"]

    @pytest.mark.anyio()
    async def test_wiki_log_read_returns_entries(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dataclasses import replace
        from server.lib import config as config_mod
        original = config_mod.load_config

        def fake_load_config():
            cfg = original()
            return replace(cfg, wiki_dir=tmp_path)

        monkeypatch.setattr("server.lib.config.load_config", fake_load_config)

        await wiki_log_append(action="test", title="entry1", body="body1")
        result = json.loads(await wiki_log_read())
        assert "entries" in result
        assert any(e["title"] == "entry1" for e in result["entries"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_w1.py::TestLogToolsAsync -v`
Expected: FAIL — `wiki_log_append` is sync; `await` on a sync result is a TypeError.

- [ ] **Step 3: Convert `tools/log.py` functions to async**

In `plugins/wiki/server/server/tools/log.py`:

1. Add to imports: `import anyio`.
2. Add to imports: `from server.lib.storage import WikiLockTimeoutError`.
3. Replace `wiki_log_append` (around line 28-45):

```python
async def wiki_log_append(action: str, title: str, body: str = "") -> str:
    """Append an entry to log.md.

    Format: `## [YYYY-MM-DD] <action> | <title>` followed by optional body + blank line.
    """
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    log_path = wiki_dir / LOG_FILENAME
    today = date.today().isoformat()
    header = f"## [{today}] {action} | {title}\n"
    entry = header + (body + "\n" if body else "") + "\n"
    try:
        async with storage.wiki_lock(wiki_dir):
            await anyio.to_thread.run_sync(_do_log_write, wiki_dir, log_path, entry)
        return json.dumps({"entry": entry.strip(), "path": str(log_path)})
    except WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})


def _do_log_write(wiki_dir: Path, log_path: Path, entry: str) -> None:
    """Sync helper: filesystem ops on a worker thread."""
    wiki_dir.mkdir(parents=True, exist_ok=True)
    existing = log_path.read_text() if log_path.exists() else ""
    storage.atomic_write(log_path, existing + entry)
```

4. Convert `wiki_log_read` to async (no lock needed, but signature must be async for consistency w/ fastmcp registration):

```python
async def wiki_log_read(
    since: str | None = None,
    action_filter: str | None = None,
    limit: int = 0,
) -> str:
    """Read log entries, optionally filtered."""
    cfg = config_mod.load_config()
    log_path = cfg.wiki_dir / LOG_FILENAME

    def _do_read() -> dict:
        if not log_path.exists():
            return {"entries": []}
        content = log_path.read_text()
        entries: list[dict[str, Any]] = []
        matches = list(_ENTRY_RE.finditer(content))
        for i, m in enumerate(matches):
            entry_date, action, title = m.group(1), m.group(2), m.group(3)
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
            body_text = content[start:end].strip()
            if since and entry_date < since:
                continue
            if action_filter and action != action_filter:
                continue
            entries.append({"date": entry_date, "action": action, "title": title, "body": body_text})
        if limit > 0 and len(entries) > limit:
            entries = entries[-limit:]
        return {"entries": entries}

    result = await anyio.to_thread.run_sync(_do_read)
    return json.dumps(result)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_w1.py::TestLogToolsAsync -v`
Expected: PASS (2/2).

- [ ] **Step 5: Commit**

```bash
git add plugins/wiki/server/server/tools/log.py plugins/wiki/server/tests/test_wiki_lock_w1.py
git commit -m "refactor(wiki/log): wiki_log_append + wiki_log_read async + lock_timeout JSON"
```

---

## Task 6: Convert `tools/index.py` to async

**Files:**
- Modify: `plugins/wiki/server/server/tools/index.py`

- [ ] **Step 1: Read current `wiki_index_rebuild` to identify the heavy work**

Run: `cat /home/raul/projects/claude-project-manager/plugins/wiki/server/server/tools/index.py | head -120`. Identify:
- The body that walks pages (rglob), reads frontmatter, computes counts — this is the CPU/IO-bound work to push to a worker thread.
- The atomic_write to `index.md` — happens inside the lock.

- [ ] **Step 2: Convert `wiki_index_rebuild` to async**

In `plugins/wiki/server/server/tools/index.py`:

1. Add imports: `import anyio`, `from server.lib.storage import WikiLockTimeoutError`.
2. Replace `wiki_index_rebuild` body. Wrap the existing pre-lock work in a sync helper called via `await anyio.to_thread.run_sync(...)`. The helper returns the rendered string + summary stats; the async fn then takes the lock + writes:

```python
async def wiki_index_rebuild() -> str:
    """Rebuild index.md from all pages. Heavy work runs on a worker thread."""
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    try:
        # Heavy: walk pages, read frontmatter, sort, render. Worker thread.
        rendered_text, counts, recent_count = await anyio.to_thread.run_sync(
            _build_index_text, wiki_dir
        )
        # Lock + write: critical section. Both ops on worker thread.
        async with storage.wiki_lock(wiki_dir):
            await anyio.to_thread.run_sync(
                storage.atomic_write, wiki_dir / INDEX_FILENAME, rendered_text
            )
        return json.dumps({
            "entries_by_category": counts,
            "recent_count": recent_count,
        })
    except WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})


def _build_index_text(wiki_dir: Path) -> tuple[str, dict[str, int], int]:
    """Sync helper: walk pages, build index.md text, return (text, counts, recent_count)."""
    # Move the existing body of wiki_index_rebuild that builds `lines` here.
    # Returns (rendered_text, counts_by_category, recent_count).
    # Implementer: extract from current wiki_index_rebuild body lines that:
    # - rglob pages, parse frontmatter, organize by category
    # - sort, format header lines, recent section
    # - finally returns the joined rendered_text and stats.
    ...
```

(The implementer should extract the existing body into the helper. The current function is around lines 45-113; everything before `with storage.wiki_lock(wiki_dir):` becomes the helper body.)

3. Convert `wiki_index_read` similarly (read-only, no lock needed but still async for fastmcp consistency):

```python
async def wiki_index_read() -> str:
    """Read index.md + return content + parsed category counts + recent list."""
    cfg = config_mod.load_config()
    index_path: Path = cfg.wiki_dir / INDEX_FILENAME

    def _do_read() -> dict:
        if not index_path.exists():
            return {"content": "", "categories": {}, "recent": []}
        content = index_path.read_text()
        # ... existing parsing logic ...
        return {"content": content, ...}

    result = await anyio.to_thread.run_sync(_do_read)
    return json.dumps(result)
```

(Implementer extracts existing wiki_index_read body into the `_do_read` helper.)

- [ ] **Step 3: Add tool tests**

Append to `plugins/wiki/server/tests/test_wiki_lock_w1.py`:

```python
class TestIndexToolsAsync:
    @pytest.mark.anyio()
    async def test_wiki_index_rebuild_returns_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dataclasses import replace
        from server.lib import config as config_mod

        def fake_load_config():
            return replace(config_mod.load_config(), wiki_dir=tmp_path)

        monkeypatch.setattr("server.lib.config.load_config", fake_load_config)
        # Create one page so rebuild has content
        pages = tmp_path / "pages" / "concepts"
        pages.mkdir(parents=True)
        (pages / "x.md").write_text("---\ntitle: x\ntags: []\nlinks_to: []\nscope: []\nsources: []\nlast_ingested: 2026-04-26\n---\nbody\n")

        from server.tools.index import wiki_index_rebuild
        result = json.loads(await wiki_index_rebuild())
        assert "entries_by_category" in result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_w1.py::TestIndexToolsAsync -v`
Expected: PASS (1/1).

- [ ] **Step 5: Commit**

```bash
git add plugins/wiki/server/server/tools/index.py plugins/wiki/server/tests/test_wiki_lock_w1.py
git commit -m "refactor(wiki/index): wiki_index_rebuild + wiki_index_read async + worker-thread offload"
```

---

## Task 7: Convert `tools/page.py` to async

**Files:**
- Modify: `plugins/wiki/server/server/tools/page.py`

- [ ] **Step 1: Convert `wiki_page_write` to async**

In `plugins/wiki/server/server/tools/page.py`:

1. Add imports: `import anyio`, `from server.lib.storage import WikiLockTimeoutError`.
2. Convert `wiki_page_write` (around line 44):

```python
async def wiki_page_write(
    slug: str,
    category: str | None,
    frontmatter: dict[str, Any],
    body: str,
    mode: str = "upsert",
) -> str:
    """Create, update, or upsert a wiki page."""
    cfg = config_mod.load_config()
    wiki_dir: Path = cfg.wiki_dir

    # Pre-lock validation — pure computation, runs on event loop fine.
    missing = _validate_frontmatter(frontmatter)
    if missing:
        return json.dumps({"error": f"missing required frontmatter fields: {missing}"})

    try:
        profile = profile_mod.load_profile(wiki_dir)
    except profile_mod.ProfileError as e:
        return json.dumps({"error": f"profile load failed: {e}"})

    warning: str | None = None
    if profile.categories and category and category not in profile.categories:
        warning = (
            f"category {category!r} not in active profile ({profile.name}): {profile.categories}"
        )

    target = storage.page_path(wiki_dir, category, slug)
    exists = target.exists()
    if mode == "create" and exists:
        return json.dumps({"error": f"page exists at {target}"})
    if mode == "update" and not exists:
        return json.dumps({"error": f"not_found: {target} does not exist"})
    if mode not in {"create", "update", "upsert"}:
        return json.dumps({"error": f"invalid mode: {mode!r}"})

    new_content = fm_mod.dump(frontmatter, body)

    try:
        async with storage.wiki_lock(wiki_dir):
            outcome = await anyio.to_thread.run_sync(
                _do_page_write, target, frontmatter, body, new_content, mode
            )
        outcome["warning"] = warning
        return json.dumps(outcome)
    except WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})


def _do_page_write(
    target: Path,
    frontmatter: dict[str, Any],
    body: str,
    new_content: str,
    mode: str,
) -> dict:
    """Sync helper: locked-region work on worker thread."""
    locked_exists = target.exists()
    if mode == "upsert" and locked_exists:
        existing_raw = target.read_text()
        existing_fm, existing_body = fm_mod.parse(existing_raw)
        if _content_hash(existing_fm, existing_body) == _content_hash(frontmatter, body):
            return {
                "path": str(target),
                "created": False,
                "updated": False,
                "noop": True,
            }
    storage.atomic_write(target, new_content)
    return {
        "path": str(target),
        "created": not locked_exists,
        "updated": locked_exists,
        "noop": False,
    }
```

3. Convert `wiki_page_get`, `wiki_page_list` to async (read-only, no lock):

```python
async def wiki_page_get(slug: str, category: str | None) -> str:
    cfg = config_mod.load_config()
    target = storage.page_path(cfg.wiki_dir, category, slug)

    def _do_get() -> dict:
        if not target.exists():
            return {"error": "not_found", "path": str(target)}
        try:
            fm, body = fm_mod.parse(target.read_text())
        except fm_mod.FrontmatterError as e:
            return {"error": f"frontmatter parse failed: {e}", "path": str(target)}
        return {"frontmatter": fm, "body": body, "path": str(target)}

    return json.dumps(await anyio.to_thread.run_sync(_do_get))
```

`wiki_page_list` similarly: extract its body into a `_do_list` sync helper, await via `anyio.to_thread.run_sync`.

4. Convert `wiki_page_delete`:

```python
async def wiki_page_delete(slug: str, category: str | None) -> str:
    cfg = config_mod.load_config()
    wiki_dir: Path = cfg.wiki_dir
    target = storage.page_path(wiki_dir, category, slug)
    if not target.exists():
        return json.dumps({"error": "not_found", "path": str(target)})

    try:
        async with storage.wiki_lock(wiki_dir):
            updated_backlinks = await anyio.to_thread.run_sync(
                _do_page_delete, wiki_dir, target, slug
            )
        return json.dumps({
            "deleted": True,
            "backlinks_updated": updated_backlinks,
            "path": str(target),
        })
    except WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})


def _do_page_delete(wiki_dir: Path, target: Path, slug: str) -> list[str]:
    """Sync helper: backlink prune + delete, on worker thread."""
    updated_backlinks: list[str] = []
    pages_root = storage.pages_dir(wiki_dir)
    for md in pages_root.rglob("*.md"):
        if md == target:
            continue
        try:
            fm, body = fm_mod.parse(md.read_text())
        except fm_mod.FrontmatterError:
            continue
        links: list[str] = cast("list[str]", fm.get("links_to", []) or [])
        if slug in links:
            new_links = [link for link in links if link != slug]
            fm["links_to"] = new_links
            storage.atomic_write(md, fm_mod.dump(fm, body))
            updated_backlinks.append(md.stem)
    target.unlink()
    return updated_backlinks
```

- [ ] **Step 2: Add tool tests**

Append to `plugins/wiki/server/tests/test_wiki_lock_w1.py`:

```python
class TestPageToolsAsync:
    @pytest.mark.anyio()
    async def test_wiki_page_write_returns_json(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from dataclasses import replace
        from server.lib import config as config_mod

        def fake_load_config():
            return replace(config_mod.load_config(), wiki_dir=tmp_path)

        monkeypatch.setattr("server.lib.config.load_config", fake_load_config)

        from server.tools.page import wiki_page_write
        result = json.loads(await wiki_page_write(
            slug="test",
            category="concepts",
            frontmatter={"title": "T", "tags": [], "links_to": [], "scope": [], "sources": [], "last_ingested": "2026-04-26"},
            body="hello",
            mode="create",
        ))
        assert result["created"] is True
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_w1.py::TestPageToolsAsync -v`
Expected: PASS (1/1).

- [ ] **Step 4: Commit**

```bash
git add plugins/wiki/server/server/tools/page.py plugins/wiki/server/tests/test_wiki_lock_w1.py
git commit -m "refactor(wiki/page): wiki_page_* async + worker-thread offload + lock_timeout JSON"
```

---

## Task 8: Convert `tools/search.py` to async + restructure lock acquisition around bm25

**Files:**
- Modify: `plugins/wiki/server/server/tools/search.py`

- [ ] **Step 1: Convert `wiki_search_index_refresh` (the explicit rebuild)**

In `plugins/wiki/server/server/tools/search.py`:

1. Add imports: `import anyio`, `from server.lib.storage import WikiLockTimeoutError`.
2. Replace `wiki_search_index_refresh` (currently around line 110):

```python
async def wiki_search_index_refresh() -> str:
    """Force full rebuild of the BM25 sidecar index."""
    cfg = config_mod.load_config()
    try:
        start = time.monotonic()
        async with storage.wiki_lock(cfg.wiki_dir):
            idx = await anyio.to_thread.run_sync(bm25_mod.rebuild_index, cfg.wiki_dir)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return json.dumps({"pages_indexed": idx.doc_count, "elapsed_ms": elapsed_ms})
    except WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})
```

- [ ] **Step 2: Convert `wiki_search_bm25` (lazy-rebuild path)**

`wiki_search_bm25` calls `bm25_mod.load_or_rebuild` which may invoke `rebuild_index`. After Task 4's change, rebuild_index requires the caller to hold the lock. Need to restructure:

Option A: split `load_or_rebuild` into "is_stale check" + "load if fresh" + "rebuild if stale" — caller holds the lock only when rebuilding.
Option B: always hold the lock around `load_or_rebuild` in `wiki_search_bm25`. Simpler; minor perf cost on uncontended paths since the lock IS acquired even for stale-cache loads.

Recommend Option B for simplicity + correctness:

```python
async def wiki_search_bm25(
    query: str,
    limit: int = 60,
    category: str | None = None,
    tags: list[str] | None = None,
    scope_filter: str | None = None,
) -> str:
    """BM25 keyword search over wiki pages."""
    cfg = config_mod.load_config()
    try:
        async with storage.wiki_lock(cfg.wiki_dir):
            idx = await anyio.to_thread.run_sync(bm25_mod.load_or_rebuild, cfg.wiki_dir)

        # Filtering + ranking happens outside the lock — pure computation on cached index.
        def _do_search() -> list[dict]:
            raw_hits = idx.query(query, top_k=limit * 3 if (category or tags or scope_filter) else limit)
            query_tokens = bm25_mod.tokenize(query)
            tag_set = set(tags or [])
            results: list[dict[str, Any]] = []
            for hit in raw_hits:
                found, cat, fm, body = _page_metadata(cfg.wiki_dir, hit["slug"])
                if not found:
                    continue
                if category and cat != category:
                    continue
                page_tags = set(fm.get("tags", []) or [])
                if tag_set and not tag_set.issubset(page_tags):
                    continue
                page_scope: list[str] = fm.get("scope", []) or []
                if scope_filter and scope_filter not in page_scope:
                    continue
                results.append({
                    "slug": hit["slug"],
                    "score": hit["score"],
                    "snippet": _extract_snippet(body, query_tokens),
                    "category": cat,
                    "tags": list(page_tags),
                    "scope": page_scope,
                })
                if len(results) >= limit:
                    break
            return results

        results = await anyio.to_thread.run_sync(_do_search)
        return json.dumps({"hits": results})
    except WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})
```

- [ ] **Step 3: Add tool test**

Append to `plugins/wiki/server/tests/test_wiki_lock_w1.py`:

```python
class TestSearchToolsAsync:
    @pytest.mark.anyio()
    async def test_wiki_search_index_refresh_returns_json(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from dataclasses import replace
        from server.lib import config as config_mod

        def fake_load_config():
            return replace(config_mod.load_config(), wiki_dir=tmp_path)

        monkeypatch.setattr("server.lib.config.load_config", fake_load_config)
        pages = tmp_path / "pages" / "concepts"
        pages.mkdir(parents=True)
        (pages / "x.md").write_text("---\ntitle: x\ntags: []\nlinks_to: []\nscope: []\nsources: []\nlast_ingested: 2026-04-26\n---\nbody\n")

        from server.tools.search import wiki_search_index_refresh
        result = json.loads(await wiki_search_index_refresh())
        assert "pages_indexed" in result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_w1.py::TestSearchToolsAsync -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/wiki/server/server/tools/search.py plugins/wiki/server/tests/test_wiki_lock_w1.py
git commit -m "refactor(wiki/search): wiki_search_* async + lock around bm25 + lock_timeout JSON"
```

---

## Task 9: Convert `tools/links.py` and `tools/scope.py` to async (read-only, signature only)

**Files:**
- Modify: `plugins/wiki/server/server/tools/links.py`
- Modify: `plugins/wiki/server/server/tools/scope.py`

- [ ] **Step 1: Convert `wiki_link_resolve`**

In `plugins/wiki/server/server/tools/links.py`, change:

```python
def wiki_link_resolve(link: str) -> str:
    # ... existing body ...
```

To:

```python
async def wiki_link_resolve(link: str) -> str:
    import anyio

    def _do_resolve() -> dict:
        # Move existing body here, returning the dict that was being json.dumps()'d
        ...
    return json.dumps(await anyio.to_thread.run_sync(_do_resolve))
```

(Implementer extracts the existing function body verbatim into `_do_resolve`. Since the original function ends with `return json.dumps({...})`, the helper returns the dict and the wrapper json.dumps it.)

- [ ] **Step 2: Convert `wiki_scope_detect`**

Same pattern in `plugins/wiki/server/server/tools/scope.py`:

```python
async def wiki_scope_detect() -> str:
    import anyio

    def _do_detect() -> dict:
        # Move existing body here
        ...
    return json.dumps(await anyio.to_thread.run_sync(_do_detect))
```

- [ ] **Step 3: Run existing wiki test suite**

Run: `cd plugins/wiki/server && uv run pytest tests/ -v 2>&1 | tail -20`
Expected: any tests using `wiki_link_resolve` or `wiki_scope_detect` will fail (need `await`). Note them; will be fixed in Task 12.

- [ ] **Step 4: Commit**

```bash
git add plugins/wiki/server/server/tools/links.py plugins/wiki/server/server/tools/scope.py
git commit -m "refactor(wiki/links,scope): convert wiki_link_resolve + wiki_scope_detect to async"
```

---

## Task 10: Convert `tools/lint.py` (7 wiki_lint_* fns) to async

**Files:**
- Modify: `plugins/wiki/server/server/tools/lint.py`

- [ ] **Step 1: Add `import anyio` at top of lint.py**

- [ ] **Step 2: Convert each of the 7 lint fns**

For each of: `wiki_lint_orphans`, `wiki_lint_broken_links`, `wiki_lint_broken_section_refs`, `wiki_lint_category_violations`, `wiki_lint_stale`, `wiki_lint_schema`, `wiki_lint_duplicates`:

Apply the same pattern as Task 9 — wrap existing sync body in a `_do_<name>` helper, make the registered fn `async`, dispatch via `await anyio.to_thread.run_sync(_do_<name>)`.

Example for `wiki_lint_orphans` (currently around line 75-100):

```python
async def wiki_lint_orphans() -> str:
    """..."""

    def _do_lint() -> dict:
        # Move existing body here. Returns the dict that was being json.dumps()'d.
        ...

    return json.dumps(await anyio.to_thread.run_sync(_do_lint))
```

Repeat for all 7 lint functions. (Lint functions are read-only — no lock needed.)

- [ ] **Step 3: Verify with grep**

Run: `grep -E '^def (wiki_lint|async def wiki_lint)' /home/raul/projects/claude-project-manager/plugins/wiki/server/server/tools/lint.py`
Expected: 7 lines, all starting with `async def wiki_lint_`.

- [ ] **Step 4: Commit**

```bash
git add plugins/wiki/server/server/tools/lint.py
git commit -m "refactor(wiki/lint): convert 7 wiki_lint_* fns to async + worker-thread offload"
```

---

## Task 11: Audit + remove old references

**Files:**
- Modify: `plugins/wiki/server/server/lib/storage.py` (verify deletes from Task 3)
- Other wiki files as needed

- [ ] **Step 1: Confirm no `threading.RLock` / `_HELD_LOCKS` / `with_wiki_lock` remain**

Run:
```bash
grep -rn 'threading.RLock\|_HELD_LOCKS\|with_wiki_lock' plugins/wiki/server/
```

Expected: ZERO matches. If any remain, clean them up.

- [ ] **Step 2: Confirm all wiki tool fns are async**

Run:
```bash
grep -rn '^def wiki_' plugins/wiki/server/server/tools/
```

Expected: ZERO matches (all should be `async def wiki_`). If any remain, convert them.

- [ ] **Step 3: Confirm no `with storage.wiki_lock\|with wiki_lock` remain**

Run:
```bash
grep -rn 'with storage.wiki_lock\|with wiki_lock' plugins/wiki/server/
```

Expected: ZERO matches. The old sync-context-manager usage must all be `async with`.

- [ ] **Step 4: Commit any cleanup**

If audits surfaced anything to fix:
```bash
git add -u
git commit -m "chore(wiki): cleanup stragglers from W1 async migration"
```

If clean, no commit.

---

## Task 12: Migrate existing wiki tests to async

**Files:**
- Modify: `plugins/wiki/server/tests/*.py` (all that exercise wiki tools)

- [ ] **Step 1: Run full wiki test suite to find failures**

Run: `cd plugins/wiki/server && uv run pytest 2>&1 | tail -50`
Expected: Many failures from tests calling sync `wiki_*` fns; errors will mention coroutine objects, missing `await`, etc.

- [ ] **Step 2: For each failing test, add `pytest.mark.anyio()` + `await`**

For each test file in `plugins/wiki/server/tests/`:
1. If it tests a wiki tool, add `@pytest.mark.anyio()` to each test fn.
2. Make the test fn `async def`.
3. Add `await` before each call to `wiki_*` tool fn.

Use this systematic pattern. Implementer iterates: run test suite → fix one test file → re-run → repeat until green.

- [ ] **Step 3: Run full wiki test suite**

Run: `cd plugins/wiki/server && uv run pytest 2>&1 | tail -10`
Expected: ALL tests pass. Coverage threshold (85%) maintained.

- [ ] **Step 4: Commit**

```bash
git add plugins/wiki/server/tests/
git commit -m "test(wiki): migrate all tests to async API + pytest.mark.anyio"
```

---

## Task 13: Add event-loop responsiveness test

**Files:**
- Test: append to `plugins/wiki/server/tests/test_wiki_lock_w1.py`

- [ ] **Step 1: Append responsiveness test**

```python
class TestEventLoopResponsiveness:
    @pytest.mark.anyio()
    async def test_event_loop_responsive_during_index_rebuild(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """While wiki_index_rebuild runs, concurrent anyio sleeps complete fast."""
        from dataclasses import replace
        from server.lib import config as config_mod

        def fake_load_config():
            return replace(config_mod.load_config(), wiki_dir=tmp_path)

        monkeypatch.setattr("server.lib.config.load_config", fake_load_config)

        # Populate w/ enough pages so rebuild has work
        pages = tmp_path / "pages" / "concepts"
        pages.mkdir(parents=True)
        for i in range(50):
            (pages / f"page-{i}.md").write_text(
                f"---\ntitle: page-{i}\ntags: []\nlinks_to: []\nscope: []\nsources: []\nlast_ingested: 2026-04-26\n---\nbody-{i}\n"
            )

        elapsed_for_quick: list[float] = []

        async def quick_op() -> None:
            start = time.monotonic()
            await anyio.sleep(0.001)
            elapsed_for_quick.append(time.monotonic() - start)

        from server.tools.index import wiki_index_rebuild

        async with anyio.create_task_group() as tg:
            tg.start_soon(wiki_index_rebuild)
            await anyio.sleep(0.1)  # let rebuild start
            for _ in range(10):
                tg.start_soon(quick_op)

        assert max(elapsed_for_quick) < 0.5, (
            f"event loop stalled (max quick op took {max(elapsed_for_quick):.3f}s, "
            f"all values: {elapsed_for_quick})"
        )
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd plugins/wiki/server && uv run pytest tests/test_wiki_lock_w1.py::TestEventLoopResponsiveness -v`
Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add plugins/wiki/server/tests/test_wiki_lock_w1.py
git commit -m "test(wiki): event-loop responsiveness test during long wiki_index_rebuild"
```

---

## Task 14: Final verification

- [ ] **Step 1: Confirm dispatch.py UNCHANGED**

Run: `git log --oneline -- plugins/_shared/hook_dispatch/dispatch.py | head -5`
Expected: most recent entry is from before this batch (no new commits in this branch).

Run: `git diff main..HEAD --stat plugins/_shared/`
Expected: NO files changed in `_shared/` (or only files unrelated to dispatch.py).

- [ ] **Step 2: Run full wiki test suite**

Run: `cd plugins/wiki/server && uv run pytest -v 2>&1 | tail -15`
Expected: ALL tests pass; coverage ≥ 85%.

- [ ] **Step 3: Run lint + type check**

Run:
```bash
cd plugins/wiki/server && uv run ruff check . && uv run ruff format --check .
uv run basedpyright server tests
```
Expected: clean.

- [ ] **Step 4: Run full proj plugin test suite (sanity — should be unaffected)**

Run: `cd plugins/proj/server && uv run pytest 2>&1 | tail -5`
Expected: ALL pass (proj is unchanged by W1; sanity check only).

- [ ] **Step 5: Commit any formatting fixes**

If ruff/basedpyright surfaced fixes:
```bash
git add -u
git commit -m "style: ruff/basedpyright fixes for wiki W1 migration"
```

---

## Acceptance criteria recap

1. **Mutex correctness**: 2 anyio tasks calling `wiki_lock` serialize correctly. **Task 3 step 1 (test_two_tasks_serialize)**.
2. **Reentry detection**: `WikiLockReentryError` raised on nested call. **Task 3 step 1 (test_reentry_raises)**.
3. **Cross-process exclusion**: external subprocess holding flock blocks the in-process caller. **Task 3 step 1 (test_cross_process_blocks_until_released)**.
4. **Cross-process timeout**: budget expiry raises `WikiLockTimeoutError`; tools return `{"error": "lock_timeout", ...}` JSON. **Task 3 (test_cross_process_timeout_raises) + Task 5/6/7/8 tool tests**.
5. **Event loop responsive**: concurrent quick ops complete fast during long wiki tool. **Task 13**.
6. **All 6 lock-using tools return valid JSON under load**. **Tasks 5/6/7/8 + Task 12 migration**.
7. **Existing wiki test suite passes**. **Task 12 + Task 14**.
8. **dispatch.py UNCHANGED**. **Task 14 step 1**.
9. **No `threading.RLock` / `_HELD_LOCKS` / `with_wiki_lock` references**. **Task 11**.
