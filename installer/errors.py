"""Error handling and robustness utilities for the installer."""

from __future__ import annotations

import contextlib
import fcntl
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import IO

logger = logging.getLogger("installer.errors")

# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class InstallerError(Exception):
    """Base exception for all installer errors."""

    exit_code: int = 2

    def __init__(self, message: str, *, exit_code: int | None = None) -> None:
        super().__init__(message)
        if exit_code is not None:
            self.exit_code = exit_code


class UserCancelled(InstallerError):
    """User chose to cancel the operation."""

    exit_code: int = 1

    def __init__(self, message: str = "Cancelled by user.") -> None:
        super().__init__(message, exit_code=1)


class PrerequisiteError(InstallerError):
    """A required tool or dependency is missing."""

    pass


class NetworkError(InstallerError):
    """A network operation failed."""

    retryable: bool = True

    def __init__(
        self, message: str, *, retryable: bool = True, exit_code: int | None = None
    ) -> None:
        super().__init__(message, exit_code=exit_code)
        self.retryable = retryable


class LockError(InstallerError):
    """Could not acquire the installer lock."""

    pass


# ---------------------------------------------------------------------------
# Prerequisite checks
# ---------------------------------------------------------------------------

_UV_INSTALL_CMD = "curl -LsSf https://astral.sh/uv/install.sh | sh"


def check_prerequisites() -> None:
    """Verify that required tools are available on PATH.

    Raises PrerequisiteError if ``claude`` is missing.
    Offers to auto-install ``uv`` via curl if missing (raises on refusal).
    """
    if shutil.which("claude") is None:
        raise PrerequisiteError(
            "Claude Code CLI ('claude') not found on PATH. "
            "Install it from https://docs.anthropic.com/en/docs/claude-code"
        )

    if shutil.which("uv") is None:
        print("'uv' package manager not found on PATH.")
        answer = input("Install uv automatically? [Y/n] ").strip().lower()
        if answer in ("", "y", "yes"):
            try:
                subprocess.run(
                    ["sh", "-c", _UV_INSTALL_CMD],
                    check=True,
                    timeout=30,
                )
            except subprocess.TimeoutExpired as exc:
                raise NetworkError("uv install timed out after 30 seconds.") from exc
            except subprocess.CalledProcessError as exc:
                raise PrerequisiteError(
                    f"Failed to install uv (exit {exc.returncode}). "
                    "Install manually: https://docs.astral.sh/uv/"
                ) from exc
            # Verify it landed on PATH after install
            if shutil.which("uv") is None:
                raise PrerequisiteError(
                    "uv was installed but is not on PATH. "
                    "You may need to restart your shell or add ~/.local/bin to PATH."
                )
        else:
            raise UserCancelled("uv is required. Install it and retry.")


# ---------------------------------------------------------------------------
# Root-user check
# ---------------------------------------------------------------------------


def check_root() -> None:
    """Warn if running as root (UID 0) and require confirmation to proceed.

    Raises UserCancelled if the user declines.
    """
    if os.getuid() == 0:
        print("WARNING: Running as root (UID 0) is not recommended.")
        answer = input("Continue anyway? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            raise UserCancelled("Aborted — do not run the installer as root.")


# ---------------------------------------------------------------------------
# Lock file
# ---------------------------------------------------------------------------

_LOCK_FILENAME = "cpm-install.lock"
_MAX_LOCK_RETRIES = 2


def acquire_lock() -> IO:
    """Acquire an exclusive file lock to prevent concurrent installer runs.

    Writes the current PID into the lock file for stale-lock detection.
    Retries up to *_MAX_LOCK_RETRIES* times.

    Returns the open file handle (caller must keep it alive and close it to
    release the lock).

    Raises LockError if the lock cannot be acquired after retries.
    """
    lock_path = Path(tempfile.gettempdir()) / _LOCK_FILENAME

    for attempt in range(1 + _MAX_LOCK_RETRIES):
        try:
            # Open (or create) the lock file
            lock_fh = lock_path.open("w")
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            # Write our PID for diagnostics
            lock_fh.write(str(os.getpid()))
            lock_fh.flush()
            return lock_fh
        except OSError:
            # Lock held by another process — check for stale PID
            try:
                with lock_path.open() as f:
                    holder_pid = int(f.read().strip())
                # Check if the holding process is still alive
                os.kill(holder_pid, 0)
            except (ValueError, OSError, ProcessLookupError):
                # PID is stale or unreadable — remove and retry
                with contextlib.suppress(OSError):
                    lock_path.unlink(missing_ok=True)
                continue

            if attempt < _MAX_LOCK_RETRIES:
                logger.warning(
                    "Another installer is running (PID %d). Retry %d/%d...",
                    holder_pid,
                    attempt + 1,
                    _MAX_LOCK_RETRIES,
                )
                continue

            lock_fh.close()
            raise LockError(
                f"Could not acquire lock — another installer is running "
                f"(PID {holder_pid}, lock: {lock_path})."
            ) from None

    raise LockError(f"Could not acquire installer lock after retries ({lock_path}).")


def release_lock(lock_fh: IO | None) -> None:
    """Release and clean up the lock file."""
    if lock_fh is None:
        return
    try:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
        lock_fh.close()
    except OSError:
        pass
    try:
        lock_path = Path(tempfile.gettempdir()) / _LOCK_FILENAME
        lock_path.unlink(missing_ok=True)
    except OSError:
        pass
