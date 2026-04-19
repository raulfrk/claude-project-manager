"""Tests for installer/app.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


class TestPrepareAndReinstallBuildsInstallPlan:
    """_prepare_and_reinstall builds an InstallPlan and exits the app."""

    @pytest.mark.asyncio
    async def test_reinstall_builds_plan_with_installed_plugins(self):
        """_prepare_and_reinstall must build a reinstall plan with authoritative plugins."""
        from installer.app import InstallerApp
        from installer.detect import InstallState
        from installer.flow.install_plan import InstallPlan

        authoritative = [
            "proj@claude-project-manager",
            "router@claude-project-manager",
        ]

        with (
            patch(
                "installer.app.get_installed_plugins",
                return_value=authoritative,
            ),
            patch("installer.app.get_available_plugins", return_value=authoritative),
        ):
            app = InstallerApp()
            app._state = InstallState(installed_plugins=["hooks", "proj", "router"])
            app.exit = MagicMock()  # type: ignore[method-assign]

            await app._prepare_and_reinstall(reset_configs=False)

            app.exit.assert_called_once()
            assert app.install_plan is not None
            assert isinstance(app.install_plan, InstallPlan)
            # Both plugins should be in the plan as reinstall actions
            action_ids = [a.plugin_id for a in app.install_plan.actions]
            action_kinds = [a.action for a in app.install_plan.actions]
            assert "proj@claude-project-manager" in action_ids
            assert "router@claude-project-manager" in action_ids
            assert all(k == "reinstall" for k in action_kinds)

    @pytest.mark.asyncio
    async def test_reinstall_empty_sets_message_and_exits(self):
        """With no installed plugins, sets reinstall_message and exits."""
        from installer.app import InstallerApp
        from installer.detect import InstallState

        with patch("installer.app.get_installed_plugins", return_value=[]):
            app = InstallerApp()
            app._state = InstallState(installed_plugins=[])
            app.exit = MagicMock()  # type: ignore[method-assign]

            await app._prepare_and_reinstall(reset_configs=False)

            app.exit.assert_called_once()
            assert app.install_plan is None
            assert app.reinstall_message is not None
            assert "Nothing to reinstall" in app.reinstall_message

    @pytest.mark.asyncio
    async def test_reinstall_query_failure_sets_message_and_exits(self):
        """If get_installed_plugins fails, sets error reinstall_message and exits."""
        from installer.app import InstallerApp
        from installer.detect import InstallState
        from installer.errors import InstallerError

        with patch(
            "installer.app.get_installed_plugins",
            side_effect=InstallerError("CLI timeout"),
        ):
            app = InstallerApp()
            app._state = InstallState(installed_plugins=[])
            app.exit = MagicMock()  # type: ignore[method-assign]

            await app._prepare_and_reinstall(reset_configs=False)

            app.exit.assert_called_once()
            assert app.install_plan is None
            assert app.reinstall_message is not None
            assert "Failed to query installed plugins" in app.reinstall_message


class TestStartStatusInstall:
    """Exercise ``InstallerApp._start_status_install`` — now builds InstallPlan."""

    def test_start_status_install_builds_plan_and_exits(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_start_status_install must build an InstallPlan and call exit()."""
        from installer.app import InstallerApp
        from installer.flow.install_plan import InstallPlan

        monkeypatch.setattr(
            "installer.app.get_available_plugins",
            lambda: [
                "router@claude-project-manager",
                "proj@claude-project-manager",
                "jira@claude-project-manager",
            ],
        )
        monkeypatch.setattr(
            "installer.app.get_installed_plugins",
            lambda: ["proj@claude-project-manager", "jira@claude-project-manager"],
        )

        app = InstallerApp()
        app.exit = MagicMock()  # type: ignore[method-assign]
        app._pending_actions = [
            ("router", "install"),
            ("proj", "reinstall"),
            ("jira", "uninstall"),
        ]

        app._start_status_install()

        app.exit.assert_called_once()
        assert isinstance(app.install_plan, InstallPlan)
        action_kinds = {a.plugin_id: a.action for a in app.install_plan.actions}
        assert action_kinds["router@claude-project-manager"] == "install"
        assert action_kinds["proj@claude-project-manager"] == "reinstall"
        assert action_kinds["jira@claude-project-manager"] == "uninstall"

    def test_start_status_install_empty_exits_without_plan(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no pending actions, must exit without building a plan."""
        from installer.app import InstallerApp

        app = InstallerApp()
        app.exit = MagicMock()  # type: ignore[method-assign]
        app._pending_actions = []

        app._start_status_install()

        app.exit.assert_called_once()
        assert app.install_plan is None


class TestPrepareAndReinstallPrunesStaleCache:
    """_prepare_and_reinstall runs scan + prune before building the install plan."""

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

        monkeypatch.setattr(
            "installer.app.get_installed_plugins",
            lambda: ["proj@claude-project-manager"],
            raising=False,
        )
        monkeypatch.setattr(
            "installer.app.get_available_plugins",
            lambda: ["proj@claude-project-manager"],
            raising=False,
        )

        # Auto-confirm orphan removal
        async def _confirm_yes(self, names):
            return True

        monkeypatch.setattr(
            InstallerApp, "_confirm_orphans", _confirm_yes, raising=False
        )

        app = InstallerApp(mode="reinstall")
        app._state = type("S", (), {})()
        app.exit = MagicMock()  # type: ignore[method-assign]

        await app._prepare_and_reinstall(reset_configs=False)

        # Stale version 3.0.0 removed; live version 5.0.0 kept; orphan sandbox removed
        assert not (cache / "proj" / "3.0.0").exists()
        assert (cache / "proj" / "5.0.0").is_dir()
        assert not (cache / "sandbox").exists()
        # Plan was built and app exited
        assert app.exit.called
        assert app.install_plan is not None


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


class TestOnUpdateSelected:
    """Exercise ``InstallerApp._on_update_selected`` — now builds InstallPlan."""

    def test_update_selected_builds_plan_with_qualified_ids(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_on_update_selected must build an update plan with qualified plugin IDs."""
        from installer.app import InstallerApp
        from installer.detect import InstallState
        from installer.flow.install_plan import InstallPlan

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
        app._state = InstallState(installed_plugins=["proj", "router", "worktree"])
        app.exit = MagicMock()  # type: ignore[method-assign]

        app._on_update_selected(["proj"])

        app.exit.assert_called_once()
        assert isinstance(app.install_plan, InstallPlan)
        assert len(app.install_plan.actions) == 1
        assert app.install_plan.actions[0].plugin_id == "proj@claude-project-manager"
        assert app.install_plan.actions[0].action == "update"

    def test_update_selected_fallback_when_plugin_absent_from_lists(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When plugin is not in available/installed lists, falls back to default ID."""
        from installer.app import InstallerApp
        from installer.detect import InstallState

        monkeypatch.setattr("installer.app.get_available_plugins", lambda: [])
        monkeypatch.setattr("installer.app.get_installed_plugins", lambda: [])

        app = InstallerApp()
        app._state = InstallState(installed_plugins=[])
        app.exit = MagicMock()  # type: ignore[method-assign]

        app._on_update_selected(["weird_plugin"])

        assert app.install_plan is not None
        assert (
            app.install_plan.actions[0].plugin_id
            == "weird_plugin@claude-project-manager"
        )
        assert app.install_plan.actions[0].action == "update"

    def test_update_selected_enumeration_failure_falls_back_gracefully(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If get_available_plugins raises, fallback IDs are used — no crash."""
        from installer.app import InstallerApp
        from installer.detect import InstallState
        from installer.errors import InstallerError

        monkeypatch.setattr(
            "installer.app.get_available_plugins",
            lambda: (_ for _ in ()).throw(InstallerError("CLI timeout")),
        )
        monkeypatch.setattr("installer.app.get_installed_plugins", lambda: [])

        app = InstallerApp()
        app._state = InstallState(installed_plugins=[])
        app.exit = MagicMock()  # type: ignore[method-assign]

        app._on_update_selected(["proj"])

        assert app.install_plan is not None
        assert app.install_plan.actions[0].plugin_id == "proj@claude-project-manager"
        assert app.install_plan.actions[0].action == "update"


class TestEmitResyncRunbooks:
    """Verify the runbook-surfacing helper emits a user-readable block
    when any collected runner has a resync_failure whose message indicates
    a missing Todoist api_token."""

    def test_runbook_printed_when_token_missing(self) -> None:
        import io

        from installer.app import _emit_resync_runbooks
        from installer.migrations.integrations.base import Action, FailedAction
        from installer.flow.migration_summary import MigrationOutcome

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
        from installer.flow.migration_summary import MigrationOutcome

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
        from installer.flow.migration_summary import MigrationOutcome

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


class TestRunSqlPhaseHelper:
    """Unit tests for the _run_sql_phase module-level helper."""

    def _make_project(self, version: int, tmp_path) -> "object":
        """Return a PendingProject-like object at the given schema version."""

        from installer.migrations.types import PendingProject

        proj_dir = tmp_path / f"proj_v{version}"
        proj_dir.mkdir(parents=True, exist_ok=True)
        sv_path = proj_dir / ".schema-version"
        if version >= 2:
            sv_path.write_text(f"{version}\n")
        return PendingProject(
            name=f"proj_v{version}",
            path=proj_dir,
            schema_version_path=sv_path,
            current_version=version,
        )

    def test_v2_project_calls_sql_migration_and_returns_ok(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """v2 project → SqlOnlyMigration runs through all phases → (True, None)."""
        from installer.app import _run_sql_phase

        plan_called = []
        confirm_called = []
        execute_called = []
        commit_called = []

        class _MockSqlOnlyMigration:
            def __init__(self, **kwargs):
                self._kwargs = kwargs

            def plan(self):
                plan_called.append(True)

            def confirm(self, confirmed: bool = True):
                confirm_called.append(confirmed)

            def execute_local(self):
                execute_called.append(True)

            def commit(self):
                commit_called.append(True)

        monkeypatch.setattr(
            "installer.migrations.sql_only.SqlOnlyMigration", _MockSqlOnlyMigration
        )

        project = self._make_project(2, tmp_path)
        ok, err = _run_sql_phase(project, "test-ts", tmp_path / "backups")

        assert ok is True
        assert err is None
        assert len(plan_called) == 1
        assert confirm_called == [True]
        assert len(execute_called) == 1
        assert len(commit_called) == 1

    def test_v3_project_is_noop_no_migration_runs(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """v3 project (already migrated) → returns (True, None) without running anything."""
        from installer.app import _run_sql_phase

        instantiated = []

        class _MockSqlOnlyMigration:
            def __init__(self, **kwargs):
                instantiated.append(True)

        monkeypatch.setattr(
            "installer.migrations.sql_only.SqlOnlyMigration", _MockSqlOnlyMigration
        )

        project = self._make_project(3, tmp_path)
        ok, err = _run_sql_phase(project, "test-ts", tmp_path / "backups")

        assert ok is True
        assert err is None
        assert len(instantiated) == 0  # migration class never instantiated

    def test_v1_project_returns_error_without_running_migration(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """v1 project → returns (False, error msg) without running SqlOnlyMigration."""
        from installer.app import _run_sql_phase

        instantiated = []

        class _MockSqlOnlyMigration:
            def __init__(self, **kwargs):
                instantiated.append(True)

        monkeypatch.setattr(
            "installer.migrations.sql_only.SqlOnlyMigration", _MockSqlOnlyMigration
        )

        project = self._make_project(1, tmp_path)
        ok, err = _run_sql_phase(project, "test-ts", tmp_path / "backups")

        assert ok is False
        assert err is not None
        assert "v1" in err
        assert len(instantiated) == 0  # migration class never instantiated

    def test_sql_migration_exception_returns_error_tuple(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """SqlOnlyMigration raises → returns (False, str(exc)) without propagating."""
        from installer.app import _run_sql_phase

        class _FailingMigration:
            def __init__(self, **kwargs):
                pass

            def plan(self):
                raise RuntimeError("db locked")

            def confirm(self, confirmed: bool = True):
                pass

            def execute_local(self):
                pass

            def commit(self):
                pass

        monkeypatch.setattr(
            "installer.migrations.sql_only.SqlOnlyMigration", _FailingMigration
        )

        project = self._make_project(2, tmp_path)
        ok, err = _run_sql_phase(project, "test-ts", tmp_path / "backups")

        assert ok is False
        assert err == "db locked"
