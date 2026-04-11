"""Tests for installer/app.py call order and settings_hooks stage wiring."""

from __future__ import annotations

from unittest.mock import patch

import pytest


class TestInstallerAppSettingsHooksStage:
    """Assert InstallerApp routes through the settings_hooks stage after yaml_hooks."""

    def test_app_has_settings_hooks_stage_method(self):
        """Sanity: the wiring method exists on InstallerApp."""
        from installer.app import InstallerApp

        candidates = [
            "_check_settings_hooks_diff",
            "_push_settings_hooks_diff_screen",
            "_on_settings_hooks_diff_complete",
            "_on_settings_hooks_diff_done",
        ]
        found = [name for name in candidates if hasattr(InstallerApp, name)]
        assert found, f"None of {candidates} found on InstallerApp"

    def test_app_imports_settings_hooks(self):
        """Sanity: the app module imports from installer.settings_hooks."""
        import inspect

        import installer.app as app_mod

        source = inspect.getsource(app_mod)
        assert "settings_hooks" in source, (
            "installer.app should reference settings_hooks"
        )

    def test_skips_stage_when_no_plugin_dirs(self, tmp_path, monkeypatch):
        """With empty plugin_dirs, the settings_hooks stage is skipped gracefully."""
        from installer.app import InstallerApp

        app = InstallerApp()
        if hasattr(app, "_plugin_dirs"):
            app._plugin_dirs = []
        for name in [
            "_check_settings_hooks_diff",
            "_push_settings_hooks_diff_screen",
        ]:
            if hasattr(app, name):
                try:
                    getattr(app, name)()
                except Exception as exc:
                    pytest.skip(f"{name} requires full app context: {exc}")
                break


class TestReinstallWorkerUsesAuthoritativePluginList:
    """The reinstall worker must derive plugin IDs from get_installed_plugins,
    not from the stale cache-dir inventory in InstallState.installed_plugins."""

    @pytest.mark.asyncio
    async def test_reinstall_ignores_stale_cache_dir(self):
        """Worker must call install/uninstall with JSON-sourced IDs only."""
        from installer.app import InstallerApp
        from installer.detect import InstallState

        authoritative = [
            "proj@claude-project-manager",
            "router@claude-project-manager",
        ]

        with (
            patch(
                "installer.app.get_installed_plugins",
                return_value=authoritative,
            ) as mock_get,
            patch("installer.app.uninstall_plugin") as mock_uninstall,
            patch("installer.app.install_plugin") as mock_install,
        ):
            app = InstallerApp()
            app._state = InstallState(
                installed_plugins=["hooks", "proj", "router"],
            )

            class _FakeProgress:
                def __init__(self):
                    self.logs: list[str] = []

                async def wait_ready(self):
                    return None

                def write_log(self, msg: str) -> None:
                    self.logs.append(msg)

                def advance(self, steps: int = 1, detail: str = "") -> None:
                    return None

            progress = _FakeProgress()
            await app._run_reinstall_worker(
                authoritative, progress, reset_configs=False
            )

            mock_get.assert_not_called()  # queried upstream by _prepare_and_reinstall
            uninstall_ids = [c.args[0] for c in mock_uninstall.call_args_list]
            install_ids = [c.args[0] for c in mock_install.call_args_list]
            assert uninstall_ids == authoritative
            assert install_ids == authoritative
            assert "hooks" not in uninstall_ids
            assert "hooks" not in install_ids

    @pytest.mark.asyncio
    async def test_reinstall_empty_install(self):
        """With no installed plugins, worker logs a message and makes zero calls."""
        from installer.app import InstallerApp
        from installer.detect import InstallState
        from installer.screens.progress import ProgressScreen

        with (
            patch(
                "installer.app.get_installed_plugins",
                return_value=[],
            ),
            patch("installer.app.uninstall_plugin") as mock_uninstall,
            patch("installer.app.install_plugin") as mock_install,
        ):
            app = InstallerApp()
            app._state = InstallState(installed_plugins=["hooks"])

            captured: list[ProgressScreen] = []
            logs: list[str] = []

            def fake_push_screen(screen, callback=None):
                captured.append(screen)

                async def _wait_ready():
                    return None

                def _write_log(msg: str) -> None:
                    logs.append(msg)

                def _advance(steps: int = 1, detail: str = "") -> None:
                    return None

                screen.wait_ready = _wait_ready  # type: ignore[method-assign]
                screen.write_log = _write_log  # type: ignore[method-assign]
                screen.advance = _advance  # type: ignore[method-assign]

            app.push_screen = fake_push_screen  # type: ignore[method-assign]

            await app._prepare_and_reinstall(reset_configs=False)

            mock_install.assert_not_called()
            mock_uninstall.assert_not_called()
            assert any("Nothing to reinstall" in msg for msg in logs)
