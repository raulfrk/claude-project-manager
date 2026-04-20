"""Terminal-state save/restore guard for the installer.

Captures termios attributes at process entry and restores them on exit.
Without this, any subprocess or prompt-toolkit dialog that leaves stdin
in raw mode (ICRNL cleared, ICANON off, ECHO off) strands the user's
terminal — Enter echoes as ``^M`` and ``input()`` hangs waiting for a
line-feed that will never arrive.

Two-stage restore:
  1. ``termios.tcsetattr`` with the saved attributes (preferred — exact).
  2. ``stty sane`` via subprocess (fallback — pragmatic).
  3. ANSI ``\\x1b[?25h`` emitted to stdout so Rich Progress panics
     don't leave the cursor hidden.

All operations are best-effort: if stdin is not a tty, or termios is
unavailable (Windows), the guard no-ops.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from typing import Any, Iterator


def _fileno() -> int | None:
    """Return stdin fileno if it is a real TTY, else None."""
    try:
        fd = sys.stdin.fileno()
    except (ValueError, OSError, AttributeError):
        return None
    try:
        if not os.isatty(fd):
            return None
    except OSError:
        return None
    return fd


def _save(fd: int) -> Any | None:
    try:
        import termios
    except ImportError:
        return None
    try:
        return termios.tcgetattr(fd)
    except termios.error:
        return None


def _restore(fd: int, saved: Any | None) -> bool:
    if saved is None:
        return False
    try:
        import termios
    except ImportError:
        return False
    try:
        termios.tcsetattr(fd, termios.TCSANOW, saved)
        return True
    except termios.error:
        return False


def _stty_sane(fd: int) -> None:
    """Best-effort fallback: run `stty sane` against fd."""
    try:
        subprocess.run(
            ["stty", "sane"],
            stdin=fd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=2,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass


def _show_cursor() -> None:
    """Emit DECTCEM show-cursor so a crashed Rich Progress can't leave it hidden."""
    try:
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()
    except (OSError, ValueError):
        pass


@contextlib.contextmanager
def tty_guard() -> Iterator[None]:
    """Save termios on enter, restore on exit.

    No-op when stdin is not a TTY (CI, piped input) or termios is absent.
    """
    fd = _fileno()
    saved = _save(fd) if fd is not None else None
    try:
        yield
    finally:
        if fd is not None:
            if not _restore(fd, saved):
                _stty_sane(fd)
            _show_cursor()
