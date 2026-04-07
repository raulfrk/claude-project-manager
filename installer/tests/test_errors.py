"""Tests for installer.errors — error handling, locks, prerequisites."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from installer.errors import (
    InstallerError,
    LockError,
    NetworkError,
    PrerequisiteError,
    UserCancelled,
    acquire_lock,
    check_prerequisites,
    check_root,
    release_lock,
)


class TestExceptionHierarchy:
    def test_installer_error_default_exit_code(self):
        err = InstallerError("boom")
        assert err.exit_code == 2

    def test_installer_error_custom_exit_code(self):
        err = InstallerError("boom", exit_code=42)
        assert err.exit_code == 42

    def test_user_cancelled_exit_code(self):
        err = UserCancelled()
        assert err.exit_code == 1
        assert "Cancelled" in str(err)

    def test_user_cancelled_custom_message(self):
        err = UserCancelled("nope")
        assert str(err) == "nope"

    def test_prerequisite_error_is_installer_error(self):
        assert issubclass(PrerequisiteError, InstallerError)

    def test_network_error_retryable(self):
        err = NetworkError("timeout")
        assert err.retryable is True

    def test_network_error_not_retryable(self):
        err = NetworkError("auth failed", retryable=False)
        assert err.retryable is False

    def test_lock_error_is_installer_error(self):
        assert issubclass(LockError, InstallerError)


class TestCheckPrerequisites:
    def test_missing_claude(self):
        with (
            patch("installer.errors.shutil.which", return_value=None),
            pytest.raises(PrerequisiteError, match="claude"),
        ):
            check_prerequisites()

    def test_claude_present_uv_present(self):
        with patch(
            "installer.errors.shutil.which", side_effect=lambda x: f"/usr/bin/{x}"
        ):
            check_prerequisites()  # should not raise

    def test_uv_missing_user_accepts(self):
        def mock_which(name):
            if name == "claude":
                return "/usr/bin/claude"
            if name == "uv":
                # First call: missing. After "install", present.
                mock_which._uv_calls += 1
                if mock_which._uv_calls <= 1:
                    return None
                return "/usr/bin/uv"
            return None

        mock_which._uv_calls = 0

        with (
            patch("installer.errors.shutil.which", side_effect=mock_which),
            patch("builtins.input", return_value="y"),
            patch("installer.errors.subprocess.run"),
        ):
            check_prerequisites()

    def test_uv_missing_user_declines(self):
        def mock_which(name):
            if name == "claude":
                return "/usr/bin/claude"
            return None  # uv not found

        with (
            patch("installer.errors.shutil.which", side_effect=mock_which),
            patch("builtins.input", return_value="n"),
            pytest.raises(UserCancelled, match="uv is required"),
        ):
            check_prerequisites()


class TestCheckRoot:
    def test_not_root(self):
        with patch("installer.errors.os.getuid", return_value=1000):
            check_root()  # should not raise

    def test_root_user_confirms(self):
        with (
            patch("installer.errors.os.getuid", return_value=0),
            patch("builtins.input", return_value="y"),
        ):
            check_root()  # should not raise

    def test_root_user_declines(self):
        with (
            patch("installer.errors.os.getuid", return_value=0),
            patch("builtins.input", return_value="n"),
            pytest.raises(UserCancelled, match="root"),
        ):
            check_root()


class TestLockFile:
    def test_acquire_and_release(self):
        lock_fh = acquire_lock()
        assert lock_fh is not None
        lock_path = Path(tempfile.gettempdir()) / "cpm-install.lock"
        assert lock_path.exists()

        release_lock(lock_fh)

    def test_release_none_is_noop(self):
        release_lock(None)  # should not raise

    def test_double_acquire_with_stale_pid(self, tmp_path: Path):
        """If the lock holder PID is dead, the lock is acquired after cleanup."""
        lock_fh = acquire_lock()
        lock_path = Path(tempfile.gettempdir()) / "cpm-install.lock"

        # Write a dead PID
        release_lock(lock_fh)
        lock_path.write_text("999999999")

        # Should succeed because PID 999999999 doesn't exist
        lock_fh2 = acquire_lock()
        assert lock_fh2 is not None
        release_lock(lock_fh2)
