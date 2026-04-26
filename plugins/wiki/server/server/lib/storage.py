"""Wiki filesystem helpers: path resolution, atomic writes, shared lock."""

from __future__ import annotations

import fcntl
import os
import tempfile
import time
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING

import anyio
import anyio.to_thread

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

WIKI_LOCK_TIMEOUT = 30.0  # seconds; cross-process flock acquisition budget
WIKI_LOCK_RETRY_INTERVAL = 0.1  # seconds between flock LOCK_NB retry attempts


class WikiLockReentryError(RuntimeError):
    """Raised when wiki_lock detects same-task reentry (anyio.Lock is non-reentrant)."""


class WikiLockTimeoutError(RuntimeError):
    """Raised when cross-process flock cannot be acquired within WIKI_LOCK_TIMEOUT."""


def _flock_with_timeout(fd: int, lock_path: Path) -> None:
    """Acquire fcntl.flock(LOCK_EX) with WIKI_LOCK_TIMEOUT budget.

    LOCK_NB retry loop with WIKI_LOCK_RETRY_INTERVAL between attempts.
    Reads WIKI_LOCK_TIMEOUT at call time so monkeypatched values take effect.

    Designed to run on a worker thread (called via anyio.to_thread.run_sync).
    The retry-loop sleep blocks the worker thread, not the event loop.

    Raises:
        WikiLockTimeoutError: if budget exhausted.
    """
    # Re-read module-level timeout each call so monkeypatching works in tests.
    from server.lib import storage as _storage_mod

    deadline = time.monotonic() + _storage_mod.WIKI_LOCK_TIMEOUT
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise WikiLockTimeoutError(
                    f"wiki .lock not acquired within {_storage_mod.WIKI_LOCK_TIMEOUT}s "
                    f"({lock_path}; another session/process likely holds it)"
                ) from None
            time.sleep(_storage_mod.WIKI_LOCK_RETRY_INTERVAL)


_WIKI_LOCK = anyio.Lock()  # in-process exclusion (anyio-aware, single per MCP process)
_LOCK_FILENAME = ".lock"


def pages_dir(wiki_dir: Path) -> Path:
    return wiki_dir / "pages"


def page_path(wiki_dir: Path, category: str | None, slug: str) -> Path:
    base = pages_dir(wiki_dir)
    if category:
        return base / category / f"{slug}.md"
    return base / f"{slug}.md"


def atomic_write(target: Path, content: str) -> None:
    """Write `content` to `target` atomically via tmpfile + os.replace.

    Creates parent dirs as needed.
    """
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


@asynccontextmanager
async def wiki_lock(wiki_dir: Path) -> AsyncGenerator[None, None]:
    """Acquire shared wiki lock: in-process anyio.Lock + cross-process fcntl.flock.

    Async context manager. Callers must use `async with wiki_lock(wiki_dir): ...`.

    Raises:
        WikiLockReentryError: if the calling task already holds the lock.
        WikiLockTimeoutError: if the cross-process flock cannot be acquired
            within WIKI_LOCK_TIMEOUT seconds.
    """
    owner = _WIKI_LOCK.statistics().owner
    if owner is not None and owner.id == anyio.get_current_task().id:
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
