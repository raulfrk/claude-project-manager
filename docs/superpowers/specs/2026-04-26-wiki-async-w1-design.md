# Wiki async W1 (todo 764)

**Date**: 2026-04-26
**Source todos**: 764 (wiki_lock mutex broken under concurrent fastmcp tasks). Captures work formerly tracked separately as 765 (sync MCP tool event-loop stall) — superseded by W1.
**Status**: design approved, ready for plan
**Origin**: VM-freeze re-investigation 2026-04-26 + design pivot from blanket-wrap to surgical wiki-only after user pushback. See memory `project_vm_freeze_root_cause.md`, wiki `[[wiki-only-async-fix-w1-over-blanket-wrap-2026-04-26]]`, `[[wiki-lock-mutex-broken-anyio]]`, `[[sync-tool-event-loop-stall]]`, `[[fastmcp-threading-model]]`.

## Problem

Two real bugs surfaced during the freeze re-investigation, both rooted in fastmcp's threading model (single asyncio event loop on a single OS thread, concurrent requests dispatched as anyio tasks via `tg.start_soon`).

### Bug 1: `wiki_lock` mutex broken

`plugins/wiki/server/server/lib/storage.py:50-84` uses `_WIKI_LOCK = threading.RLock()` + `_HELD_LOCKS = threading.local()`. Both per-OS-thread. Two concurrent anyio tasks on the same thread:

- Task A acquires RLock + flock, stores fd in `_HELD_LOCKS.fds`. Awaits → yields.
- Task B: same thread → RLock reentrant succeeds. `_HELD_LOCKS.fds` has fd → `is_first_acquire = False` → reuses fd, **skips flock** → enters critical section concurrently with A.

Mutual exclusion completely broken. Manifests as data races / corruption (concurrent `wiki_page_write` could corrupt index.md), NOT freeze. Repro at `/tmp/wikitest_lock/repro.py`.

### Bug 2: sync MCP tools stall the event loop

`plugins/_shared/hook_dispatch/dispatch.py:610-623` — sync handler is called inline on the event-loop thread (`fn(*args, **kwargs)` at line 613). fastmcp does NOT auto-threadpool sync tools (verified by reading `mcp/server/fastmcp/utilities/func_metadata.py:74-95` + GitHub issue [#1839](https://github.com/modelcontextprotocol/python-sdk/issues/1839)). While any sync handler runs CPU-bound work, the entire event loop stalls. Examples: `wiki_index_rebuild` (1.4s on 125 pages), BM25 build (0.13s), lint passes (variable).

## Decision: surgical W1 over blanket-wrap

Two fixes were considered:

- **Blanket-wrap** (originally tracked as 765): change `dispatch.py:613` to `await anyio.to_thread.run_sync(fn, *args)`. Fixes ALL sync tools across all 7 plugins. Project-wide blast radius: requires audit for `threading.local`, module-mutable state, embedded `asyncio.run` in every plugin.
- **W1 surgical (chosen)**: convert wiki plugin's ~20 tool fns to `async def` + use `anyio.Lock` for in-process exclusion + push blocking work to worker threads via `await anyio.to_thread.run_sync(_helper, *args)` *inside the wiki plugin*. `dispatch.py` UNCHANGED. Other 6 plugins UNCHANGED.

Rationale (full version: wiki page `[[wiki-only-async-fix-w1-over-blanket-wrap-2026-04-26]]`):
- Wiki is the only plugin with measured event-loop stall. Other 6 plugins have no evidence of the problem.
- Smallest blast radius: 0 `_shared/` files, 1 plugin's tests need a verification pass, no audit needed across 7 plugins.
- Reversibility: revert = wiki commit only.
- Cost: 20 fn signatures + ~10 lines of helper code in wiki, vs 6 lines in `dispatch.py` + project-wide audit.

If proj/router/other plugins ever ship a CPU-bound sync tool, revisit with the blanket-wrap pattern (documented in superseded todo 765 notes).

## Multi-session correctness: LOCK_NB + 30s retry on the cross-process flock

Multiple Claude sessions = multiple top-level claude processes = each spawns its own wiki MCP server. Both wiki MCPs operate on shared `~/.claude/wiki/.lock`. Without bounding, session B's `await anyio.to_thread.run_sync(fcntl.flock, fd, LOCK_EX)` could block its worker thread indefinitely if session A holds the flock and wedges.

Fix: replace blocking `fcntl.flock(fd, LOCK_EX)` with a retry loop using `LOCK_EX | LOCK_NB`, sleeping 100ms between attempts, total budget 30s. On expiry, raise `WikiLockTimeoutError` which the calling MCP tool catches and returns as `{"error": "lock_timeout", "detail": "..."}` JSON.

This is the pattern the deleted 759 spec proposed. It was wrong as a freeze fix (no cross-process contention existed when there was only one wiki MCP) but right as a multi-session safety bound for W1.

## Solution overview

1. **`wiki_lock` becomes async context manager.** `anyio.Lock` for in-process exclusion. `fcntl.flock` (via `await anyio.to_thread.run_sync`) for cross-process exclusion with LOCK_NB + 30s retry.
2. **`WikiLockReentryError`** — anyio.Lock is non-reentrant. Detect same-task reentry via `_WIKI_LOCK.statistics().owner is anyio.get_current_task()`; raise loud RuntimeError with migration message.
3. **`WikiLockTimeoutError`** — flock budget expiry (30s). Each MCP tool wraps its body in try/except; returns `{"error": "lock_timeout", ...}` JSON.
4. **Convert all wiki MCP tool fns to `async def`** — fastmcp natively supports both. `lib/bm25.py` callers move the lock acquisition out into the async tool (cleaner separation: bm25 helpers stay sync; caller holds the lock).
5. **Push blocking work to worker thread** via `await anyio.to_thread.run_sync(_helper, *args)` inside each tool. Examples: BM25 build, file walks (rglob), atomic writes, page reads + frontmatter parsing.

## Layer 1: refactored `wiki_lock` context manager

In `plugins/wiki/server/server/lib/storage.py`:

### Constants and exception classes

```python
import anyio
import fcntl
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

WIKI_LOCK_TIMEOUT = 30.0  # seconds for cross-process flock acquisition budget
WIKI_LOCK_RETRY_INTERVAL = 0.1  # seconds between flock LOCK_NB retry attempts

_WIKI_LOCK = anyio.Lock()  # in-process exclusion (single instance per MCP process)
_LOCK_FILENAME = ".lock"


class WikiLockReentryError(RuntimeError):
    """Raised when wiki_lock detects same-task reentry (anyio.Lock is non-reentrant)."""


class WikiLockTimeoutError(RuntimeError):
    """Raised when cross-process flock cannot be acquired within WIKI_LOCK_TIMEOUT."""
```

### `_flock_with_timeout` helper (sync — invoked via `to_thread`)

```python
def _flock_with_timeout(fd: int, lock_path: Path) -> None:
    """LOCK_NB retry loop. Raises WikiLockTimeoutError on budget expiry.

    Runs on a worker thread (called via anyio.to_thread.run_sync). The retry
    loop blocks the worker thread, not the event loop.

    Reads WIKI_LOCK_TIMEOUT at call time so monkeypatched values take effect.
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

### Refactored `wiki_lock` context manager

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
            # Best-effort unlock + close; suppress errors so the original
            # exception (if any) propagates.
            try:
                await anyio.to_thread.run_sync(fcntl.flock, fd, fcntl.LOCK_UN)
            except OSError:
                pass
            await anyio.to_thread.run_sync(os.close, fd)
```

### Removed

- `_WIKI_LOCK = threading.RLock()` (replaced with anyio.Lock).
- `_HELD_LOCKS = threading.local()` (the broken cache; deleted).
- `with_wiki_lock` decorator at storage.py:91-106 (deleted; callers use `async with` directly).

The old `atomic_write` helper at storage.py:33-47 stays sync (pure I/O); callers wrap it in `await anyio.to_thread.run_sync(...)` when invoking from async context.

## Layer 2: convert wiki MCP tools to `async def`

Pattern for every lock-using tool: signature becomes `async def`. Lock acquisition becomes `async with`. Body wrapped in `try / except WikiLockTimeoutError as exc: return json.dumps({"error": "lock_timeout", "detail": str(exc)})`. CPU/IO-bound work moved to a sync helper called via `await anyio.to_thread.run_sync(_helper, *args)`.

### Example: `wiki_log_append` (tools/log.py)

Before (sync):
```python
def wiki_log_append(action: str, title: str, body: str = "") -> str:
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
```

After (async + W1):
```python
async def wiki_log_append(action: str, title: str, body: str = "") -> str:
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
    except storage.WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})


def _do_log_write(wiki_dir: Path, log_path: Path, entry: str) -> None:
    """Sync helper: filesystem ops on a worker thread."""
    wiki_dir.mkdir(parents=True, exist_ok=True)
    existing = log_path.read_text() if log_path.exists() else ""
    storage.atomic_write(log_path, existing + entry)
```

### Example: `wiki_index_rebuild` (tools/index.py — the 1.4s offender)

```python
async def wiki_index_rebuild() -> str:
    cfg = config_mod.load_config()
    wiki_dir = cfg.wiki_dir
    try:
        # Heavy: collect entries, sort, format. CPU + I/O. Worker thread.
        rendered = await anyio.to_thread.run_sync(_collect_and_render_index, wiki_dir)
        # Lock + write: critical section, but write itself is small.
        # Both operations on worker thread (lock acquisition + atomic_write).
        async with storage.wiki_lock(wiki_dir):
            await anyio.to_thread.run_sync(_write_index, wiki_dir, rendered)
        return json.dumps({"entries_by_category": rendered.counts, "recent_count": rendered.recent_count})
    except storage.WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})
```

`_collect_and_render_index` returns a small dataclass with the rendered string + summary stats; `_write_index` does the atomic_write. Both pure-sync helpers in tools/index.py.

### `bm25.py` lock-acquisition moved out

`plugins/wiki/server/server/lib/bm25.py:119` currently calls `with storage.wiki_lock(wiki_dir):` inside `rebuild_index`. Move that lock acquisition to the calling async tool:

Before (bm25.py):
```python
def rebuild_index(wiki_dir: Path) -> BM25Index:
    ...
    with storage.wiki_lock(wiki_dir):
        storage.atomic_write(sidecar, json.dumps(data, separators=(",", ":")))
    idx = BM25Index(docs=docs)
    idx.build()
    return idx
```

After (bm25.py — caller now holds lock):
```python
def rebuild_index(wiki_dir: Path) -> BM25Index:
    """Caller must hold wiki_lock (caller's responsibility now)."""
    ...
    storage.atomic_write(sidecar, json.dumps(data, separators=(",", ":")))
    idx = BM25Index(docs=docs)
    idx.build()
    return idx
```

After (tools/search.py — caller acquires lock):
```python
async def wiki_search_index_refresh() -> str:
    cfg = config_mod.load_config()
    try:
        start = time.monotonic()
        async with storage.wiki_lock(cfg.wiki_dir):
            idx = await anyio.to_thread.run_sync(bm25_mod.rebuild_index, cfg.wiki_dir)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return json.dumps({"pages_indexed": idx.doc_count, "elapsed_ms": elapsed_ms})
    except storage.WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})
```

`load_or_rebuild` (called by `wiki_search_bm25`) similarly: caller wraps in `async with wiki_lock` only when rebuild is needed; sidecar reads stay lock-free.

## Layer 3: tests

`plugins/wiki/server/tests/test_wiki_lock_w1.py` (new):

### Test 1 — Mutex correctness (refutes the bug repro)

```python
@pytest.mark.anyio()
async def test_two_tasks_serialize(tmp_path):
    log: list[str] = []

    async def hold(name: str, hold_seconds: float):
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
```

### Test 2 — Reentry detection

```python
@pytest.mark.anyio()
async def test_reentry_raises(tmp_path):
    async with wiki_lock(tmp_path):
        with pytest.raises(WikiLockReentryError, match="nested wiki_lock"):
            async with wiki_lock(tmp_path):
                pass
```

### Test 3 — Cross-process flock blocks (defense-in-depth)

```python
def _hold_flock_subprocess(lock_path: str, hold_s: float, ready_path: str):
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)
    Path(ready_path).touch()
    time.sleep(hold_s)
    fcntl.flock(fd, fcntl.LOCK_UN)
    os.close(fd)


@pytest.mark.anyio()
async def test_cross_process_flock_blocks(tmp_path):
    lock_path = tmp_path / ".lock"
    lock_path.touch()
    ready = tmp_path / ".ready"
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(target=_hold_flock_subprocess, args=(str(lock_path), 1.0, str(ready)))
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
```

### Test 4 — Cross-process timeout raises WikiLockTimeoutError

```python
@pytest.mark.anyio()
async def test_cross_process_timeout(tmp_path, monkeypatch):
    monkeypatch.setattr("server.lib.storage.WIKI_LOCK_TIMEOUT", 0.5)
    lock_path = tmp_path / ".lock"
    lock_path.touch()
    ready = tmp_path / ".ready"
    ctx = multiprocessing.get_context("spawn")
    proc = ctx.Process(target=_hold_flock_subprocess, args=(str(lock_path), 2.0, str(ready)))
    proc.start()
    try:
        for _ in range(50):
            if ready.exists():
                break
            await anyio.sleep(0.02)
        with pytest.raises(WikiLockTimeoutError, match="not acquired within"):
            async with wiki_lock(tmp_path):
                pass
    finally:
        proc.join(timeout=5)
        if proc.is_alive():
            proc.terminate()
            proc.join()
```

### Test 5 — Event loop responsive during long wiki tool

```python
@pytest.mark.anyio()
async def test_event_loop_responsive_during_index_rebuild(populated_wiki):
    """While wiki_index_rebuild runs (long), quick anyio sleeps complete fast."""
    elapsed_for_quick: list[float] = []

    async def quick_op():
        start = time.monotonic()
        await anyio.sleep(0.001)
        elapsed_for_quick.append(time.monotonic() - start)

    async with anyio.create_task_group() as tg:
        tg.start_soon(wiki_index_rebuild)  # the offender
        await anyio.sleep(0.1)
        for _ in range(10):
            tg.start_soon(quick_op)

    assert max(elapsed_for_quick) < 0.1, f"event loop stalled: {elapsed_for_quick}"
```

### Tests 6-11 — Tool wrapper integration (one per lock-using tool)

For each of: `wiki_log_append`, `wiki_index_rebuild`, `wiki_page_write`, `wiki_page_delete`, `wiki_search_bm25`, `wiki_search_index_refresh`. One test per tool calling it 5x concurrently with disjoint inputs; assert all 5 return valid JSON, no corruption visible in final wiki state.

### Test 12 — Tool returns lock_timeout JSON on flock budget expiry

```python
@pytest.mark.anyio()
async def test_wiki_log_append_returns_lock_timeout_json(tmp_path, monkeypatch, held_lock_subprocess):
    monkeypatch.setattr("server.lib.storage.WIKI_LOCK_TIMEOUT", 0.5)
    result = json.loads(await wiki_log_append(action="test", title="t"))
    assert result["error"] == "lock_timeout"
    assert "not acquired" in result["detail"]
```

`held_lock_subprocess` fixture spawns a subprocess holding flock for the test duration.

## Files affected

**Modify** (wiki plugin only):
- `plugins/wiki/server/server/lib/storage.py` — add anyio.Lock, exception classes, `_flock_with_timeout`, refactor `wiki_lock` to async; delete `_WIKI_LOCK = threading.RLock()`, `_HELD_LOCKS = threading.local()`, `with_wiki_lock` decorator.
- `plugins/wiki/server/server/lib/bm25.py` — drop the `with wiki_lock` inside `rebuild_index` (caller's responsibility).
- `plugins/wiki/server/server/tools/log.py` — `wiki_log_append`, `wiki_log_read` async.
- `plugins/wiki/server/server/tools/index.py` — `wiki_index_rebuild`, `wiki_index_read` async.
- `plugins/wiki/server/server/tools/page.py` — `wiki_page_write`, `wiki_page_get`, `wiki_page_list`, `wiki_page_delete` async.
- `plugins/wiki/server/server/tools/search.py` — `wiki_search_bm25`, `wiki_search_index_refresh` async + lock acquisition restructured.
- `plugins/wiki/server/server/tools/links.py` — `wiki_link_resolve` async.
- `plugins/wiki/server/server/tools/lint.py` — all `wiki_lint_*` async (count: ~7 functions).
- `plugins/wiki/server/server/tools/scope.py` — `wiki_scope_detect` async.
- Existing wiki tests in `plugins/wiki/server/tests/` — every test that exercises a wiki tool needs `pytest.mark.anyio()` + `await`.

**Create**:
- `plugins/wiki/server/tests/test_wiki_lock_w1.py` — new test module covering mutex, reentry, cross-process, timeout, event-loop responsiveness, tool wrappers.

**NOT affected**:
- `plugins/_shared/hook_dispatch/dispatch.py` — UNCHANGED. The blanket-wrap pattern is documented in superseded todo 765's notes.
- All other 6 plugins (proj, router, worktree, todoist, trello, jira) — UNCHANGED.

## Acceptance criteria

1. **Mutex correctness**: 2 anyio tasks calling `wiki_lock(tmp_path)` serialize correctly (B's ENTER strictly after A's EXIT in event log).
2. **Reentry detection**: nested `async with wiki_lock(tmp_path)` raises `WikiLockReentryError` with migration message.
3. **Cross-process exclusion**: external subprocess holding flock blocks `async with wiki_lock(tmp_path)` for the duration; flock released on subprocess exit (kernel-managed) unblocks the in-process caller.
4. **Cross-process timeout**: `WIKI_LOCK_TIMEOUT` budget expiry raises `WikiLockTimeoutError`. MCP tool wrapper catches and returns `{"error": "lock_timeout", "detail": "..."}` JSON.
5. **Event loop responsiveness**: while `wiki_index_rebuild` runs, concurrent `anyio.sleep(0.001)` calls complete in <100ms.
6. **No-contention performance unchanged**: single `async with wiki_lock(tmp_path)` acquire returns within ~10ms (sanity).
7. **All 6 lock-using tools return valid JSON under concurrent load** (no data corruption in final wiki state).
8. **Existing wiki test suite passes** after async API migration. Coverage threshold (85%) maintained.
9. **`dispatch.py` UNCHANGED**: `git diff --stat` shows no edits in `plugins/_shared/`.
10. **No `threading.RLock` / `_HELD_LOCKS` / `with_wiki_lock` references remain**: `grep -rn 'threading.RLock\|_HELD_LOCKS\|with_wiki_lock' plugins/wiki/server/` returns zero matches.

## Out of scope

- Other 6 plugins. If proj/router/worktree/todoist/trello/jira ever ships a CPU-bound sync tool that stalls the event loop, file a new todo using the blanket-wrap pattern from superseded 765.
- Changing fastmcp tool registration semantics — fastmcp natively supports both sync and async, no SDK changes needed.
- Replacing `bm25` library with an async-native alternative — out of scope; just wrap its sync work in `to_thread.run_sync`.
- VM freeze itself — neither this fix nor 760 are proven to cure the freeze. Host-level evidence still needed (todo 766).
- Lock-holder-pid telemetry on timeout (`/proc/locks` parse) — was in original 759 design; deferred. Add later if real cross-session timeouts need debugging.

## Cross-references

- Memory: `project_vm_freeze_root_cause.md` — full re-investigation context.
- Wiki: `[[wiki-only-async-fix-w1-over-blanket-wrap-2026-04-26]]` (decision rationale), `[[wiki-lock-mutex-broken-anyio]]` (the mutex bug), `[[sync-tool-event-loop-stall]]` (the stall bug), `[[fastmcp-threading-model]]` (load-bearing fact), `[[surgical-vs-blanket-fix-pattern]]` (meta-pattern).
- Refuted/superseded todos: 759 (LOCK_NB-only fix to wrong premise), 762 (stale-socket fix to refuted scenario), 765 (blanket-wrap dispatch.py — pattern preserved in notes for future use).
- Related: 760 (basedpyright batching, separate batch member), 766 (host-level freeze evidence capture).
- Repro: `/tmp/wikitest_lock/repro.py` (mutex bug), `/tmp/wikitest_lock/repro2.py` (event loop stall), `/tmp/wikitest_lock/repro3.py` (stale socket fast-fail).
