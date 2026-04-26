"""Wiki filesystem helpers: path resolution, atomic writes, shared lock."""

from __future__ import annotations

import fcntl
import os
import tempfile
import threading
from contextlib import contextmanager, suppress
from functools import wraps
from pathlib import Path
from typing import TYPE_CHECKING, ParamSpec, TypeVar, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

WIKI_LOCK_TIMEOUT = 30.0  # seconds; cross-process flock acquisition budget
WIKI_LOCK_RETRY_INTERVAL = 0.1  # seconds between flock LOCK_NB retry attempts


class WikiLockReentryError(RuntimeError):
    """Raised when wiki_lock detects same-task reentry (anyio.Lock is non-reentrant)."""


class WikiLockTimeoutError(RuntimeError):
    """Raised when cross-process flock cannot be acquired within WIKI_LOCK_TIMEOUT."""


_WIKI_LOCK = threading.RLock()  # re-entrant so same-thread nested wiki_lock() is fine
_LOCK_FILENAME = ".lock"
_HELD_LOCKS = threading.local()


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


@contextmanager
def wiki_lock(wiki_dir: Path) -> Generator[None, None, None]:
    """Acquire the shared wiki lock: thread-local RLock + fcntl.flock for cross-process.

    Yields once lock is held; releases on exit. Re-entrant within the same thread.
    """
    wiki_dir.mkdir(parents=True, exist_ok=True)
    lock_path = wiki_dir / _LOCK_FILENAME
    lock_path.touch(exist_ok=True)

    # Track held locks per thread to avoid re-acquiring fcntl lock on same FD
    if not hasattr(_HELD_LOCKS, "fds"):
        _HELD_LOCKS.fds = cast("dict[str, int]", {})

    _WIKI_LOCK.acquire()
    fd: int | None = None
    fds = cast("dict[str, int]", _HELD_LOCKS.fds)
    is_first_acquire = str(wiki_dir) not in fds
    try:
        if is_first_acquire:
            fd = os.open(str(lock_path), os.O_RDWR)
            fcntl.flock(fd, fcntl.LOCK_EX)
            fds[str(wiki_dir)] = fd
        else:
            fd = fds[str(wiki_dir)]
        try:
            yield
        finally:
            pass  # unlock only on final release
    finally:
        if is_first_acquire and fd is not None:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
            del fds[str(wiki_dir)]
        _WIKI_LOCK.release()


P = ParamSpec("P")
R = TypeVar("R")


def with_wiki_lock[**P, R](fn: Callable[P, R]) -> Callable[P, R]:
    """Decorator: acquire wiki_lock before fn runs.

    Expects fn's first positional arg to be the wiki_dir Path.
    """

    @wraps(fn)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        wiki_dir = args[0] if args and isinstance(args[0], Path) else kwargs.get("wiki_dir")
        if not isinstance(wiki_dir, Path):
            msg = "with_wiki_lock requires wiki_dir as first arg or kwarg"
            raise TypeError(msg)
        with wiki_lock(wiki_dir):
            return fn(*args, **kwargs)

    return wrapper
