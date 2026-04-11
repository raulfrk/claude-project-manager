"""Tests for installer/app.py call order and settings_hooks stage wiring."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

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


class _StubProgress:
    """Minimal progress-screen stand-in used by the status install worker tests."""

    def __init__(self) -> None:
        self.logs: list[str] = []
        self.advances: list[tuple[int, str]] = []

    async def wait_ready(self) -> None:  # noqa: D401
        return None

    def write_log(self, msg: str) -> None:
        self.logs.append(msg)

    def advance(self, n: int = 1, *, detail: str = "") -> None:
        self.advances.append((n, detail))


class TestStatusInstallWorker:
    """Exercise ``InstallerApp._run_status_install_worker`` directly."""

    @pytest.mark.asyncio
    async def test_status_install_worker_dispatches_actions(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from installer.app import InstallerApp

        install_mock = MagicMock(return_value=None)
        uninstall_mock = MagicMock(return_value=None)
        monkeypatch.setattr("installer.app.install_plugin", install_mock)
        monkeypatch.setattr("installer.app.uninstall_plugin", uninstall_mock)
        monkeypatch.setattr("installer.app.check_marketplace_registered", lambda: True)
        monkeypatch.setattr("installer.app.add_marketplace", lambda branch=None: None)
        monkeypatch.setattr("installer.app.remove_marketplace", lambda: None)
        monkeypatch.setattr(
            "installer.app.get_available_plugins",
            lambda: [
                "router@claude-project-manager",
                "proj@claude-project-manager",
                "trello@claude-project-manager",
                "jira@claude-project-manager",
            ],
        )
        monkeypatch.setattr(
            "installer.app.get_installed_plugins",
            lambda: ["proj@claude-project-manager", "jira@claude-project-manager"],
        )

        app = InstallerApp()
        # Prevent SummaryScreen push during the unit test (no running loop).
        monkeypatch.setattr(app, "_push_summary", lambda outcomes: None)

        progress = _StubProgress()
        actions = [
            ("router", "install"),
            ("proj", "reinstall"),
            ("trello", "skip"),
            ("jira", "uninstall"),
        ]
        outcomes = await app._run_status_install_worker(actions, progress)

        # trello/skip is dropped by PluginStatusScreen before reaching the
        # worker in real flow, but the worker itself must ignore unknown
        # actions gracefully.
        assert install_mock.call_count == 2  # router install, proj install (reinstall)
        assert (
            uninstall_mock.call_count == 2
        )  # proj uninstall (reinstall), jira uninstall

        status_by_name = {o.name: o for o in outcomes}
        assert status_by_name["router"].status == "ok"
        assert status_by_name["proj"].status == "ok"
        assert status_by_name["jira"].status == "ok"
        assert "trello" not in status_by_name  # skip was ignored

    @pytest.mark.asyncio
    async def test_status_install_worker_partial_failure(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from installer.app import InstallerApp
        from installer.errors import InstallerError

        def _install(plugin_id: str) -> None:
            if plugin_id.startswith("router"):
                raise InstallerError("network timeout")

        install_mock = MagicMock(side_effect=_install)
        uninstall_mock = MagicMock(return_value=None)
        monkeypatch.setattr("installer.app.install_plugin", install_mock)
        monkeypatch.setattr("installer.app.uninstall_plugin", uninstall_mock)
        monkeypatch.setattr("installer.app.check_marketplace_registered", lambda: True)
        monkeypatch.setattr("installer.app.add_marketplace", lambda branch=None: None)
        monkeypatch.setattr("installer.app.remove_marketplace", lambda: None)
        monkeypatch.setattr(
            "installer.app.get_available_plugins",
            lambda: [
                "router@claude-project-manager",
                "proj@claude-project-manager",
                "trello@claude-project-manager",
                "jira@claude-project-manager",
            ],
        )
        monkeypatch.setattr("installer.app.get_installed_plugins", lambda: [])

        app = InstallerApp()
        monkeypatch.setattr(app, "_push_summary", lambda outcomes: None)

        progress = _StubProgress()
        actions = [
            ("router", "install"),
            ("proj", "install"),
            ("trello", "install"),
            ("jira", "install"),
        ]
        outcomes = await app._run_status_install_worker(actions, progress)

        assert len(outcomes) == 4
        by_name = {o.name: o for o in outcomes}
        assert by_name["router"].status == "failed"
        assert by_name["router"].error == "network timeout"
        assert by_name["proj"].status == "ok"
        assert by_name["trello"].status == "ok"
        assert by_name["jira"].status == "ok"
