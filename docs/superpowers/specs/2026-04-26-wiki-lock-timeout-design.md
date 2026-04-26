# Wiki lock timeout (todo 759)

**Date**: 2026-04-26
**Source todo**: 759 — `Wiki storage.py: replace blocking flock(LOCK_EX) with LOCK_NB + retry-loop + 30s timeout (deadlock-prone across concurrent sessions)`
**Status**: design approved, ready for plan
**Origin**: VM-freeze investigation 2026-04-26 (see memory `project_vm_freeze_root_cause.md`)

## Problem

`plugins/wiki/server/server/lib/storage.py:71` calls `fcntl.flock(fd, fcntl.LOCK_EX)` — blocking, no timeout, no `LOCK_NB`. The `_WIKI_LOCK` `threading.RLock` at line 64 is also acquired without timeout.

When two same-user processes (e.g. main Claude session's wiki MCP + a `Task` subagent's wiki MCP) both try to acquire the lock concurrently, neither yields → indefinite hang. The MCP request stays open; Claude waits on the response. With no swap on the host, the kernel can soft-lock under the resulting memory pressure → visible VM freeze.

**No-contention performance is unaffected by this design.** The fix replaces "infinite wait on contention" with "30s budget on contention". On uncontended acquires, `flock(LOCK_EX | LOCK_NB)` succeeds on the first attempt at the same microsecond cost as today.

## Solution overview

1. Replace `_WIKI_LOCK.acquire()` with `_WIKI_LOCK.acquire(timeout=30)`.
2. Replace `fcntl.flock(fd, LOCK_EX)` with a retry loop using `LOCK_EX | LOCK_NB`, sleeping 100 ms between attempts, total budget 30 s.
3. On either timeout: raise a new `WikiLockTimeoutError` with a message identifying the layer (RLock vs flock) and, on flock timeout, the holder pid (parsed from `/proc/locks`, best-effort, `None` on any failure).
4. Each MCP tool that uses `wiki_lock` wraps its body to catch `WikiLockTimeoutError` and return JSON `{error: "lock_timeout", detail: "..."}` so callers see a structured error not a Python traceback.

Reentrancy via `_HELD_LOCKS.fds` per-thread is preserved unchanged.

## Layer 1: refactored `wiki_lock` context manager

In `plugins/wiki/server/server/lib/storage.py`:

### Constants

```python
WIKI_LOCK_TIMEOUT = 30.0  # seconds, applies to both RLock and flock layers
WIKI_LOCK_RETRY_INTERVAL = 0.1  # seconds between flock LOCK_NB attempts
```

### Updated context manager

```python
@contextmanager
def wiki_lock(wiki_dir: Path) -> Generator[None, None, None]:
    """Acquire the shared wiki lock with a 30s timeout on each layer.

    Raises WikiLockTimeoutError if either the per-process RLock or the
    cross-process fcntl flock cannot be acquired within WIKI_LOCK_TIMEOUT
    seconds. Re-entrant within the same thread (existing behaviour).
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

### `_flock_with_timeout` helper

```python
def _flock_with_timeout(fd: int, lock_path: Path) -> None:
    """LOCK_NB retry loop. Raises WikiLockTimeoutError on budget expiry."""
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

Add `import time` at the top of `storage.py` (currently absent).

### Invariants preserved

- Reentrancy: `is_first_acquire` check still routes nested calls to existing fd.
- Lock release order: flock unlock + fd close before RLock release (in `finally` blocks).
- No fd leak on flock-acquisition failure: `os.close(fd)` runs before re-raise.
- No RLock leak on flock-acquisition failure: outer `finally` block runs `_WIKI_LOCK.release()`.

## Layer 2: `WikiLockTimeoutError` exception class

Co-located at the top of `plugins/wiki/server/server/lib/storage.py` to avoid a one-class file:

```python
class WikiLockTimeoutError(Exception):
    """Raised when wiki_lock cannot acquire RLock or flock within budget."""
```

If the wiki module accumulates more exception classes later, can move to a dedicated `lib/exceptions.py`. YAGNI for now.

## Layer 3: holder-pid lookup via `/proc/locks`

Best-effort. Parses the kernel-exposed file lock table to find which pid holds the flock on `lock_path`'s inode.

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
                # Want FLOCK lines (not POSIX locks).
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

`/proc/locks` row format reference: kernel `fs/locks.c`. Field positions are stable across Linux 2.6+.

## Layer 4: tool wrapper pattern (catch + return JSON error)

Each MCP tool that uses `wiki_lock` (directly or via `with_wiki_lock`) wraps its body to catch `WikiLockTimeoutError` and return a structured JSON error.

### Pattern

```python
def wiki_page_write(slug, category, frontmatter, body, mode="upsert") -> str:
    try:
        # ... existing body ...
        return json.dumps({...})
    except WikiLockTimeoutError as exc:
        return json.dumps({"error": "lock_timeout", "detail": str(exc)})
```

### Affected files

Implementer audits via `grep -rn 'with wiki_lock\|@with_wiki_lock' plugins/wiki/server/server/`. Known call sites (verify completeness during plan):

- `plugins/wiki/server/server/tools/page.py` — `wiki_page_write`, `wiki_page_delete`.
- `plugins/wiki/server/server/tools/index.py` — `wiki_index_rebuild`.
- `plugins/wiki/server/server/tools/log.py` — `wiki_log_append`.
- `plugins/wiki/server/server/tools/lint.py` — any autofix lint tools that write.
- `plugins/wiki/server/server/tools/search.py` — `wiki_search_index_refresh`.

### Why per-tool wrapper, not centralized in `with_wiki_lock`

The decorator returns the wrapped function's return type (generic). Some helpers that use `wiki_lock` are not MCP tools and may not return JSON. Catching at each MCP-tool boundary keeps the JSON error format part of the tool's contract, not the lock primitive's. Less coupling.

## Tests

`plugins/wiki/server/tests/test_wiki_lock_timeout.py`:

### Test infrastructure

```python
@pytest.fixture
def fast_timeout(monkeypatch):
    """Lower the 30s production timeout to 500ms for fast unit tests."""
    monkeypatch.setattr("server.lib.storage.WIKI_LOCK_TIMEOUT", 0.5)
```

### Unit tests (single-process)

1. **test_no_contention_acquires_immediately** — sanity: `with wiki_lock(tmp_path)` succeeds with no delay (assert elapsed < 0.05 s).
2. **test_reentrant_same_thread_no_re_flock** — nested `with wiki_lock(tmp_path):` inside another `with wiki_lock(tmp_path):` re-enters via `_HELD_LOCKS.fds`. Verify the inner block executes and `_HELD_LOCKS.fds` length is 1 throughout.
3. **test_rlock_timeout_raises_with_layer_message** — spawn a thread holding `_WIKI_LOCK` for 1 s (> fast_timeout 0.5 s). Main thread's `with wiki_lock(tmp_path):` raises `WikiLockTimeoutError`; assert message contains `"RLock"`.
4. **test_flock_no_contention_under_one_second** — ensure single uncontended acquire returns in < 100 ms (sanity for retry-loop overhead in the no-contention path).
5. **test_rlock_released_after_flock_failure** — provoke flock failure (subprocess holding the file lock); assert `_WIKI_LOCK` is released after the raise (`_WIKI_LOCK.acquire(timeout=0.1)` succeeds afterward).

### Helper-function tests

6. **test_holder_pid_returns_none_when_lock_unheld** — call `_read_lock_holder_pid(tmp_path / ".lock")` with no holder; expect `None`.
7. **test_holder_pid_handles_missing_proc_locks** — monkeypatch `open("/proc/locks", ...)` to raise `OSError`; helper returns `None`.
8. **test_holder_pid_handles_malformed_lines** — monkeypatch `open` to return a fake `/proc/locks` with malformed rows; helper returns `None` (no exception).

### Cross-process integration tests

9. **test_two_subprocesses_one_times_out** — uses `multiprocessing.Process` (not threading — must exercise real cross-process flock). Process A acquires `wiki_lock(tmp_path)` and sleeps 1 s. Process B (started 100 ms after A) attempts `wiki_lock(tmp_path)` with `fast_timeout=0.5 s`; assert it raises `WikiLockTimeoutError` with `"flock"` in the message and a holder pid matching A's pid (best-effort: pid may be `None` on systems without `/proc/locks`).

### Tool-wrapper integration tests

10. **test_wiki_page_write_returns_lock_timeout_json** — fixture subprocess holds the wiki lock; call `wiki_page_write(...)` MCP tool through the standard test fixture; assert returned JSON parses to `{"error": "lock_timeout", "detail": <str containing "flock">}`.
11. **test_wiki_log_append_returns_lock_timeout_json** — same pattern with `wiki_log_append(...)`. Confirms wrapper pattern is consistent across tools.

## Files to modify

- `plugins/wiki/server/server/lib/storage.py` — add constants, exception class, `_flock_with_timeout`, `_read_lock_holder_pid`, refactor `wiki_lock`.
- `plugins/wiki/server/server/tools/page.py` — wrap `wiki_page_write`, `wiki_page_delete`.
- `plugins/wiki/server/server/tools/index.py` — wrap `wiki_index_rebuild`.
- `plugins/wiki/server/server/tools/log.py` — wrap `wiki_log_append`.
- `plugins/wiki/server/server/tools/lint.py` — wrap any lock-using autofix tools (audit during implementation).
- `plugins/wiki/server/server/tools/search.py` — wrap `wiki_search_index_refresh` if it uses the lock.
- `plugins/wiki/server/tests/test_wiki_lock_timeout.py` — new test module.

## Acceptance criteria

1. Two concurrent processes calling `wiki_lock(tmp_path)`: first holds for 1 s, second times out at 0.5 s (with `fast_timeout`) raising `WikiLockTimeoutError` containing `"flock"` and (when `/proc/locks` is available) the holder pid.
2. No-contention `wiki_lock(...)` acquire returns within 100 ms (no observable overhead vs the original blocking implementation).
3. Reentrant `with wiki_lock(...)` calls within the same thread continue to work without re-acquiring the fd.
4. After `WikiLockTimeoutError` is raised, the per-process `_WIKI_LOCK` RLock is released and an open fd is not leaked.
5. Each affected MCP tool returns `{"error": "lock_timeout", "detail": "..."}` JSON instead of propagating `WikiLockTimeoutError` to the MCP transport layer.
6. All new + existing tests in `plugins/wiki/server/tests/` pass; coverage threshold (85%) maintained.

## Out of scope

- Lock-holder telemetry beyond the pid (no command-line capture, no full process info — `lslocks` from a side terminal covers that need).
- Backporting holder-pid lookup to non-Linux platforms (returns `None` gracefully on macOS/BSD).
- Restructuring the lock primitive (no API redesign — preserve `wiki_lock` context manager + `with_wiki_lock` decorator).
- Defense against hostile callers that hold the lock indefinitely on purpose — this is a deadlock-prevention fix, not a denial-of-service guard.
- `_resolve_hooks_transport` stale-socket connect probe (todo 762, separate fix).
- `/proj:save` deferring wiki ingest (todo 761, separate fix). 759 is independently valuable as defense-in-depth even after 761 lands.

## Cross-references

- Memory: `project_vm_freeze_root_cause.md` — root-cause investigation that produced this todo.
- Reference impl: `plugins/proj/server/server/tools/todos.py:1041` — `LOCK_EX | LOCK_NB` pattern (one-shot, not retry; this spec adapts the pattern for a long-held context manager).
- Wiki page `[[batch-completion-enforcement]]` — documents the canonical `threading.Lock + fcntl.flock` cross-process locking pattern this spec follows.
- Wiki page `[[atomic-update-ref-cas-pattern]]` — documents when to prefer CAS over flock. Considered + rejected here: `wiki_lock` guards multi-step writes with no natural CAS equivalent, so flock is correct.
- Sibling todo 761: `/proj:save` defer wiki ingest off inline path. Eliminates the primary contention source. 759 is defense-in-depth for any remaining cross-process wiki access (e.g. concurrent `/wiki:ingest` from two sessions).
- Sibling todo 762: stale-socket connect probe in hook dispatch.
- Wiki page `[[parallel-orchestration-boundary-issues]]` lists cross-layer integration gaps; this fix closes one (cross-process lock contention not visible to per-todo reviewers).
