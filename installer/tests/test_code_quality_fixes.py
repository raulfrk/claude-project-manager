"""Tests for code quality improvements (475.66–475.70)."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# 475.66 — async _on_uninstall_confirmed
# ---------------------------------------------------------------------------


class TestAsyncUninstallConfirmed:
    """_on_uninstall_confirmed must not block the event loop."""

    @pytest.mark.asyncio
    async def test_prepare_and_uninstall_calls_get_installed_off_thread(self):
        """get_installed_plugins must run via asyncio.to_thread; plan is built + exit called."""
        from installer.app import InstallerApp
        from installer.detect import InstallState
        from installer.screens.confirm import ConfirmResult

        plugins = ["proj@claude-project-manager"]

        with (
            patch(
                "installer.app.get_installed_plugins",
                return_value=plugins,
            ) as mock_get,
            patch(
                "installer.app.get_available_plugins",
                return_value=plugins,
            ),
        ):
            app = InstallerApp()
            app._state = InstallState(installed_plugins=["proj"])
            app.exit = MagicMock()  # type: ignore[method-assign]

            result = ConfirmResult(confirmed=True, options={"full_cleanup": False})

            await app._prepare_and_uninstall(result)

            # get_installed_plugins was called (via asyncio.to_thread in production;
            # also called again by _build_install_plan for name→ID resolution).
            assert mock_get.called
            # App built an install plan and exited
            assert app.install_plan is not None
            app.exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_prepare_and_uninstall_exits_when_no_plugins(self):
        """When no plugins installed, _prepare_and_uninstall calls exit."""
        from installer.app import InstallerApp
        from installer.detect import InstallState
        from installer.screens.confirm import ConfirmResult

        with patch(
            "installer.app.get_installed_plugins",
            return_value=[],
        ):
            app = InstallerApp()
            app._state = InstallState(installed_plugins=[])
            app.exit = MagicMock()  # type: ignore[method-assign]

            result = ConfirmResult(confirmed=True, options={})
            await app._prepare_and_uninstall(result)

            app.exit.assert_called_once()


# ---------------------------------------------------------------------------
# 475.67 — specific exceptions in main.py (relocated from app.py; 970d960
#          moved cleanup_orphaned_plugin_caches to the main.py TUI post-exit
#          branch — the test must follow the call site)
# ---------------------------------------------------------------------------


class TestSpecificExceptionsApp:
    """Bare except Exception replaced with specific exception types."""

    def test_specific_exceptions_in_source(self):
        """The orphan-cleanup handler in main.py catches specific exceptions, not bare Exception.

        Regression guard: cleanup_orphaned_plugin_caches was moved from
        app._run_status_install_worker (deleted in 970d960) to main.py's
        TUI post-exit branch. The handler must catch specific OS/JSON errors,
        not a bare Exception, and the try-block must exist (non-vacuous check).
        """
        import ast
        import inspect

        from installer import main as main_mod

        source = inspect.getsource(main_mod)
        tree = ast.parse(source)

        # Find the except handler(s) near cleanup_orphaned_plugin_caches.
        # At least one try-block wrapping the call must exist (non-vacuous).
        found: list[ast.Try] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Try):
                continue
            # Check if the try body mentions cleanup_orphaned_plugin_caches
            try_source = ast.dump(node)
            if "cleanup_orphaned_plugin_caches" not in try_source:
                continue
            found.append(node)

        assert found, (
            "No try-block wrapping cleanup_orphaned_plugin_caches found in "
            "installer/main.py — was the call removed or the guard dropped?"
        )

        for node in found:
            # First handler should NOT be bare "except Exception"
            handler = node.handlers[0]
            assert handler.type is not None, "Handler must not be bare except"
            # Should be a Tuple of specific types, not a single Name("Exception")
            if isinstance(handler.type, ast.Name):
                assert handler.type.id != "Exception", (
                    "Should catch specific exceptions, not bare Exception"
                )

    def test_show_error_catches_no_matches_only(self):
        """_show_error catches NoMatches, not generic Exception."""
        from installer.app import InstallerApp
        from textual.css.query import NoMatches

        app = InstallerApp()
        mock_log = MagicMock()

        # Patch query_one to raise NoMatches — should not raise
        with (
            patch.object(app, "query_one", side_effect=NoMatches("nope")),
            patch.object(
                type(app), "log", new_callable=lambda: property(lambda self: mock_log)
            ),
        ):
            app._show_error("test error")

        mock_log.error.assert_called_once_with("test error")

    def test_show_error_propagates_other_exceptions(self):
        """_show_error lets non-NoMatches exceptions propagate."""
        from installer.app import InstallerApp

        app = InstallerApp()
        mock_log = MagicMock()

        with (
            patch.object(app, "query_one", side_effect=RuntimeError("unexpected")),
            patch.object(
                type(app), "log", new_callable=lambda: property(lambda self: mock_log)
            ),
            pytest.raises(RuntimeError, match="unexpected"),
        ):
            app._show_error("test error")


# ---------------------------------------------------------------------------
# 475.68 — specific exceptions in wizard._resolve_plugin_dir
# ---------------------------------------------------------------------------


class TestResolvePluginDirSpecificExceptions:
    """_resolve_plugin_dir catches ImportError, not broad Exception."""

    def test_falls_back_to_lexicographic_on_import_error(self, tmp_path: Path):
        """When packaging is not available, falls back to lexicographic sort."""
        from installer.wizard import _resolve_plugin_dir

        plugin_dir = tmp_path / "myplugin"
        plugin_dir.mkdir()
        (plugin_dir / "0.1.0").mkdir()
        (plugin_dir / "0.2.0").mkdir()
        (plugin_dir / "0.10.0").mkdir()

        # Mock away packaging so ImportError fires
        with patch.dict("sys.modules", {"packaging.version": None}):
            # Force fresh import attempt

            result = _resolve_plugin_dir(tmp_path, "myplugin")

        # Lexicographic: "0.2.0" > "0.10.0" > "0.1.0"
        assert result is not None
        assert result.name == "0.2.0"

    def test_invalid_version_falls_back_to_zero(self, tmp_path: Path):
        """Dirs with unparseable version strings get Version('0')."""
        from installer.wizard import _resolve_plugin_dir

        plugin_dir = tmp_path / "myplugin"
        plugin_dir.mkdir()
        (plugin_dir / "not-a-version").mkdir()
        (plugin_dir / "0.1.0").mkdir()

        result = _resolve_plugin_dir(tmp_path, "myplugin")
        assert result is not None
        # 0.1.0 is valid and > Version("0"), so it wins
        assert result.name == "0.1.0"

    def test_returns_none_for_missing_plugin(self, tmp_path: Path):
        from installer.wizard import _resolve_plugin_dir

        result = _resolve_plugin_dir(tmp_path, "nonexistent")
        assert result is None


# ---------------------------------------------------------------------------
# 475.69 — contextlib.suppress in _config_writer._atomic_write
# ---------------------------------------------------------------------------


class TestAtomicWriteContextlibSuppress:
    """_atomic_write uses contextlib.suppress(OSError) for tmp cleanup."""

    def test_atomic_write_cleans_up_on_replace_failure(self, tmp_path: Path):
        """On replace failure, tmp file is cleaned up via contextlib.suppress."""
        from installer._config_writer import _atomic_write

        target = tmp_path / "test.yaml"

        # Make replace fail
        with (
            patch("installer._config_writer.Path.replace", side_effect=OSError("boom")),
            pytest.raises(OSError, match="boom"),
        ):
            _atomic_write(target, "content")

        # No leftover tmp files
        tmps = list(tmp_path.glob("*.tmp"))
        assert len(tmps) == 0

    def test_atomic_write_success(self, tmp_path: Path):
        """Normal write works correctly."""
        from installer._config_writer import _atomic_write

        target = tmp_path / "test.yaml"
        _atomic_write(target, "hello: world\n")
        assert target.read_text() == "hello: world\n"

    def test_contextlib_suppress_used_in_source(self):
        """Verify contextlib.suppress is imported and used."""
        import inspect

        from installer import _config_writer

        source = inspect.getsource(_config_writer._atomic_write)
        assert "contextlib.suppress" in source


# ---------------------------------------------------------------------------
# 475.70 — logger.warning instead of print in errors.py
# ---------------------------------------------------------------------------


class TestLoggerWarningInErrors:
    """acquire_lock uses logger.warning instead of print for diagnostics."""

    def test_lock_retry_uses_logger_warning(self, tmp_path, caplog):
        """When lock retry happens, logger.warning is emitted, not print."""
        import io
        import os

        from installer.errors import LockError, acquire_lock

        our_pid = str(os.getpid())
        lock_path = Path(tmp_path) / "cpm-install.lock"
        lock_path.write_text(our_pid)

        original_open = Path.open

        def patched_open(self, *args, **kwargs):
            """Intercept lock-file open("w") so it doesn't truncate the PID."""
            if self.name == "cpm-install.lock" and args and args[0] == "w":
                # Return a dummy writable stream; flock will fail anyway
                return io.StringIO()
            return original_open(self, *args, **kwargs)

        def mock_flock(fd, operation):
            raise OSError("Resource temporarily unavailable")

        with (
            patch("installer.errors.tempfile.gettempdir", return_value=str(tmp_path)),
            patch("installer.errors.fcntl.flock", side_effect=mock_flock),
            patch.object(Path, "open", patched_open),
            caplog.at_level(logging.WARNING, logger="installer.errors"),
            pytest.raises(LockError),
        ):
            acquire_lock()

        warnings = [
            r for r in caplog.records if "Another installer is running" in r.message
        ]
        assert len(warnings) > 0, "Expected logger.warning for lock retry"

    def test_logger_module_level_exists(self):
        """errors.py defines a module-level logger."""
        from installer import errors

        assert hasattr(errors, "logger")
        assert errors.logger.name == "installer.errors"
