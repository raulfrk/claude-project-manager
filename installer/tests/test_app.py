"""Tests for installer/app.py module-level helpers.

InstallerApp class was deleted in P3 (#672). The remaining tests cover the
module-level helper functions that are still used by run_migration_tui.
"""

from __future__ import annotations


import pytest


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
