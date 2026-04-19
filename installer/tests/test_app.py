"""Tests for installer/app.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestReinstallWorkerUsesAuthoritativePluginList:
    """The reinstall worker removes marketplace, re-adds it, then installs plugins."""

    @pytest.mark.asyncio
    async def test_reinstall_uses_marketplace_remove_add(self):
        """Worker must call remove_marketplace, add_marketplace, then install each plugin."""
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
            patch("installer.app.remove_marketplace") as mock_remove,
            patch("installer.app.add_marketplace") as mock_add,
            patch("installer.app.install_plugin") as mock_install,
        ):
            app = InstallerApp()
            app._state = InstallState(
                installed_plugins=["hooks", "proj", "router"],
            )
            app._branch = None

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
            mock_remove.assert_called_once()
            mock_add.assert_called_once_with(branch=None)
            install_ids = [c.args[0] for c in mock_install.call_args_list]
            assert install_ids == authoritative
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
            patch("installer.app.remove_marketplace") as mock_remove,
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
            mock_remove.assert_not_called()
            assert any("Nothing to reinstall" in msg for msg in logs)

    @pytest.mark.asyncio
    async def test_reinstall_worker_aborts_on_remove_marketplace_failure(self):
        """If remove_marketplace fails, worker logs error and skips install phase."""
        from installer.app import InstallerApp
        from installer.detect import InstallState
        from installer.errors import InstallerError

        plugins = ["proj@claude-project-manager"]

        with (
            patch(
                "installer.app.remove_marketplace",
                side_effect=InstallerError("network error"),
            ) as mock_remove,
            patch("installer.app.add_marketplace") as mock_add,
            patch("installer.app.install_plugin") as mock_install,
        ):
            app = InstallerApp()
            app._state = InstallState(installed_plugins=["proj"])
            app._branch = None

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
            await app._run_reinstall_worker(plugins, progress, reset_configs=False)

            mock_remove.assert_called_once()
            mock_add.assert_not_called()
            mock_install.assert_not_called()
            assert any("Failed" in log or "failed" in log for log in progress.logs)


class TestOnProgressDone:
    """Tests for InstallerApp._on_progress_done NoMatches guard."""

    def test_on_progress_done_no_placeholder_does_not_raise(self) -> None:
        """_on_progress_done must silently swallow NoMatches when placeholder absent."""
        from textual.css.query import NoMatches

        from installer.app import InstallerApp

        app = InstallerApp()

        def _raise_no_matches(selector, widget_type=None):
            raise NoMatches(selector)

        app.query_one = _raise_no_matches  # type: ignore[method-assign]
        app.mode = "install"

        # Must not raise
        app._on_progress_done(None)

    def test_on_progress_done_updates_placeholder_when_present(self) -> None:
        """_on_progress_done must update placeholder text when widget is present."""
        from installer.app import InstallerApp

        app = InstallerApp()
        app.mode = "install"

        updated: list[str] = []

        class _FakePlaceholder:
            def update(self, text: str) -> None:
                updated.append(text)

        app.query_one = lambda selector, widget_type=None: _FakePlaceholder()  # type: ignore[method-assign]

        app._on_progress_done(None)

        assert updated == ["Install complete."]


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


class TestPrepareAndReinstallPrunesStaleCache:
    """_prepare_and_reinstall runs scan + prune before calling install worker."""

    @pytest.mark.asyncio
    async def test_prepare_and_reinstall_prunes_stale_cache(
        self, monkeypatch, tmp_path
    ):
        from installer.app import InstallerApp

        cache = tmp_path / "cache"
        cache.mkdir()
        for v in ("3.0.0", "5.0.0"):
            (cache / "proj" / v).mkdir(parents=True)
        (cache / "sandbox" / "1.0.0").mkdir(parents=True)
        mp = tmp_path / "marketplace.json"
        mp.write_text('{"plugins": [{"name": "proj"}]}')

        monkeypatch.setattr(
            "installer.cleanup._cache_dir_for_reinstall", lambda: cache, raising=False
        )
        monkeypatch.setattr(
            "installer.cleanup._marketplace_path_for_reinstall",
            lambda: mp,
            raising=False,
        )
        monkeypatch.setattr(
            "installer.app._cache_dir_for_reinstall", lambda: cache, raising=False
        )
        monkeypatch.setattr(
            "installer.app._marketplace_path_for_reinstall", lambda: mp, raising=False
        )

        # Stub install worker
        async def _stub_worker(self, plugins, progress, reset_configs):
            return None

        monkeypatch.setattr(
            InstallerApp, "_run_reinstall_worker", _stub_worker, raising=True
        )
        monkeypatch.setattr(
            "installer.app.get_installed_plugins",
            lambda: ["proj@claude-project-manager"],
            raising=False,
        )

        # Auto-confirm orphan removal
        async def _confirm_yes(self, names):
            return True

        monkeypatch.setattr(
            InstallerApp, "_confirm_orphans", _confirm_yes, raising=False
        )

        # Stub push_screen + state
        app = InstallerApp(mode="reinstall")
        app._state = type("S", (), {})()
        app.push_screen = lambda *a, **kw: None

        # Stub wait_ready on any progress screen
        from installer.screens.progress import ProgressScreen

        async def _stub_wait_ready(self):
            return None

        monkeypatch.setattr(
            ProgressScreen, "wait_ready", _stub_wait_ready, raising=False
        )

        await app._prepare_and_reinstall(reset_configs=False)

        # Stale version 3.0.0 removed; live version 5.0.0 kept; orphan sandbox removed
        assert not (cache / "proj" / "3.0.0").exists()
        assert (cache / "proj" / "5.0.0").is_dir()
        assert not (cache / "sandbox").exists()


class TestTodosYamlWrapperHandling:
    """_integration_badges + _count_parents_children must unwrap {"todos": [...]}."""

    def _make_project(self, tmp_path, shape: str, todos: list[dict]):
        import yaml

        proj_dir = tmp_path / "demo"
        proj_dir.mkdir()
        payload = {"todos": todos} if shape == "wrapped" else todos
        (proj_dir / "todos.yaml").write_text(yaml.safe_dump(payload))

        class _Proj:
            name = "demo"
            path = proj_dir

        return _Proj()

    def test_count_parents_children_wrapped(self, tmp_path):
        from installer.app import _count_parents_children

        proj = self._make_project(
            tmp_path,
            "wrapped",
            [
                {"id": "1", "children": ["1.1"]},
                {"id": "1.1", "parent": "1"},
                {"id": "2"},
            ],
        )
        assert _count_parents_children(proj) == (1, 1)

    def test_count_parents_children_bare_list(self, tmp_path):
        from installer.app import _count_parents_children

        proj = self._make_project(
            tmp_path,
            "bare",
            [
                {"id": "1", "children": ["1.1"]},
                {"id": "1.1", "parent": "1"},
            ],
        )
        assert _count_parents_children(proj) == (1, 1)

    def test_integration_badges_wrapped(self, tmp_path):
        from installer.app import _integration_badges

        proj = self._make_project(
            tmp_path,
            "wrapped",
            [
                {"id": "1", "todoist_task_id": "t", "jira_issue_key": "J-1"},
                {"id": "2", "trello_card_id": "c"},
            ],
        )
        badges = _integration_badges([proj], [])
        assert badges["demo"] == {"T", "R", "J"}

    def test_count_parents_children_missing_file(self, tmp_path):
        from installer.app import _count_parents_children

        proj_dir = tmp_path / "empty"
        proj_dir.mkdir()

        class _Proj:
            name = "empty"
            path = proj_dir

        assert _count_parents_children(_Proj()) == (0, 0)


class TestUpdateWorker:
    """Exercise ``InstallerApp._run_update_worker`` directly."""

    @pytest.mark.asyncio
    async def test_update_worker_uses_qualified_plugin_id(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from installer.app import InstallerApp

        update_mock = MagicMock(return_value=None)
        monkeypatch.setattr("installer.app.update_plugin", update_mock)
        monkeypatch.setattr(
            "installer.app.get_available_plugins",
            lambda: [
                "proj@claude-project-manager",
                "router@claude-project-manager",
                "worktree@claude-project-manager",
            ],
        )
        monkeypatch.setattr(
            "installer.app.get_installed_plugins",
            lambda: [
                "proj@claude-project-manager",
                "router@claude-project-manager",
                "worktree@claude-project-manager",
            ],
        )

        app = InstallerApp()
        progress = _StubProgress()
        await app._run_update_worker(["proj"], progress)

        assert update_mock.call_count == 1
        assert update_mock.call_args.args == ("proj@claude-project-manager",)

    @pytest.mark.asyncio
    async def test_update_worker_fallback_when_plugin_absent_from_lists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from installer.app import InstallerApp

        update_mock = MagicMock(return_value=None)
        monkeypatch.setattr("installer.app.update_plugin", update_mock)
        monkeypatch.setattr("installer.app.get_available_plugins", lambda: [])
        monkeypatch.setattr("installer.app.get_installed_plugins", lambda: [])

        app = InstallerApp()
        progress = _StubProgress()
        await app._run_update_worker(["weird_plugin"], progress)

        assert update_mock.call_count == 1
        assert update_mock.call_args.args == ("weird_plugin@claude-project-manager",)

    @pytest.mark.asyncio
    async def test_update_worker_continues_when_enumeration_fails(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from installer.app import InstallerApp
        from installer.errors import InstallerError

        update_mock = MagicMock(return_value=None)
        monkeypatch.setattr("installer.app.update_plugin", update_mock)

        def _raise() -> list[str]:
            raise InstallerError("CLI timeout")

        monkeypatch.setattr("installer.app.get_available_plugins", _raise)
        monkeypatch.setattr("installer.app.get_installed_plugins", lambda: [])

        app = InstallerApp()
        progress = _StubProgress()
        await app._run_update_worker(["proj"], progress)

        # Fallback still applied; no crash.
        assert update_mock.call_count == 1
        assert update_mock.call_args.args == ("proj@claude-project-manager",)
        assert any("name resolution failed" in log for log in progress.logs)


class TestEmitResyncRunbooks:
    """Verify the runbook-surfacing helper emits a user-readable block
    when any collected runner has a resync_failure whose message indicates
    a missing Todoist api_token."""

    def test_runbook_printed_when_token_missing(self) -> None:
        import io

        from installer.app import _emit_resync_runbooks
        from installer.migrations.integrations.base import Action, FailedAction
        from installer.screens.migration_progress import MigrationOutcome

        class _Runner:
            def __init__(self, failures: list[FailedAction]) -> None:
                self.resync_failures = failures

        action = Action(
            kind="clear_parent", target_id="t-1", payload={"parent_id": None}
        )
        failures = [
            FailedAction(
                action,
                "ConfigError",
                (
                    "todoist api_token not found in "
                    "~/.claude/todoist.yaml or proj.yaml. Run "
                    "`/proj:todoist-sync` on this project after "
                    "migration completes to push the flat structure "
                    "to Todoist."
                ),
                retryable=False,
            )
        ]
        runners = [_Runner(failures)]
        outcomes = [
            MigrationOutcome(project="demo", ok=True, resync_partial=True, backup="—")
        ]

        buf = io.StringIO()
        _emit_resync_runbooks(runners, outcomes, stream=buf)

        text = buf.getvalue()
        assert "Todoist resync skipped" in text
        assert "api_token not found" in text
        assert "/proj:todoist-sync" in text
        assert "demo" in text  # project name listed

    def test_runbook_silent_when_no_token_errors(self) -> None:
        import io

        from installer.app import _emit_resync_runbooks
        from installer.migrations.integrations.base import Action, FailedAction
        from installer.screens.migration_progress import MigrationOutcome

        class _Runner:
            def __init__(self, failures: list[FailedAction]) -> None:
                self.resync_failures = failures

        # Some other failure, not token-missing.
        action = Action(
            kind="clear_parent", target_id="t-1", payload={"parent_id": None}
        )
        failures = [
            FailedAction(action, "HTTPStatusError", "status=500", retryable=True)
        ]
        runners = [_Runner(failures)]
        outcomes = [
            MigrationOutcome(project="demo", ok=True, resync_partial=True, backup="—")
        ]

        buf = io.StringIO()
        _emit_resync_runbooks(runners, outcomes, stream=buf)
        assert buf.getvalue() == ""

    def test_runbook_lists_all_affected_projects(self) -> None:
        import io

        from installer.app import _emit_resync_runbooks
        from installer.migrations.integrations.base import Action, FailedAction
        from installer.screens.migration_progress import MigrationOutcome

        class _Runner:
            def __init__(self, failures: list[FailedAction]) -> None:
                self.resync_failures = failures

        action = Action(
            kind="clear_parent", target_id="t-1", payload={"parent_id": None}
        )
        token_fail = FailedAction(
            action,
            "ConfigError",
            "todoist api_token not found — run /proj:todoist-sync",
            retryable=False,
        )
        runners = [_Runner([token_fail]), _Runner([]), _Runner([token_fail])]
        outcomes = [
            MigrationOutcome(project="alpha", ok=True, resync_partial=True, backup="—"),
            MigrationOutcome(project="beta", ok=True, resync_partial=False, backup="—"),
            MigrationOutcome(project="gamma", ok=True, resync_partial=True, backup="—"),
        ]

        buf = io.StringIO()
        _emit_resync_runbooks(runners, outcomes, stream=buf)
        text = buf.getvalue()
        assert "alpha" in text
        assert "beta" not in text  # no token failure → not listed
        assert "gamma" in text
