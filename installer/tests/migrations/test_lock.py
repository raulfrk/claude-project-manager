from __future__ import annotations

import multiprocessing
import os
from pathlib import Path

import pytest

from installer.migrations.lock import LockContention, MigrationLock


def test_acquire_and_release(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    with MigrationLock(lock_path) as lk:
        assert lock_path.exists()
        assert lk.pid == os.getpid()
    # After exit the lock file's lock is released; file may remain
    # (flock releases on fd close; file staying is fine, other processes can re-acquire)


def test_second_acquire_raises(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    with MigrationLock(lock_path):
        with pytest.raises(LockContention):
            with MigrationLock(lock_path):
                pass


def _hold_lock(lock_path: str, ready_evt, release_evt) -> None:  # pragma: no cover
    from installer.migrations.lock import MigrationLock as ML

    with ML(Path(lock_path)):
        ready_evt.set()
        release_evt.wait(timeout=10)


def test_cross_process_contention(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    ready = multiprocessing.Event()
    release = multiprocessing.Event()
    p = multiprocessing.Process(
        target=_hold_lock, args=(str(lock_path), ready, release)
    )
    p.start()
    try:
        assert ready.wait(timeout=5)
        with pytest.raises(LockContention):
            with MigrationLock(lock_path):
                pass
    finally:
        release.set()
        p.join(timeout=5)


def test_holder_pid_written_to_file(tmp_path: Path) -> None:
    lock_path = tmp_path / ".lock"
    with MigrationLock(lock_path):
        assert lock_path.read_text().strip() == str(os.getpid())
