from __future__ import annotations

import fcntl
import os
from dataclasses import dataclass
from pathlib import Path


class LockContention(RuntimeError):
    """Another migration run is already in progress."""

    def __init__(self, lock_path: Path, holder_pid: str) -> None:
        super().__init__(
            f"migration lock held by pid {holder_pid} at {lock_path}",
        )
        self.lock_path = lock_path
        self.holder_pid = holder_pid


@dataclass
class MigrationLock:
    path: Path
    _fd: int | None = None
    pid: int = 0

    def __enter__(self) -> MigrationLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o644)
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            holder = _read_pid(self.path)
            os.close(self._fd)
            self._fd = None
            raise LockContention(self.path, holder) from None
        self.pid = os.getpid()
        os.ftruncate(self._fd, 0)
        os.write(self._fd, f"{self.pid}\n".encode())
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._fd is None:
            return
        try:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
        finally:
            os.close(self._fd)
            self._fd = None


def _read_pid(path: Path) -> str:
    try:
        return path.read_text().strip() or "?"
    except OSError:
        return "?"
