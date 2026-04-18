from __future__ import annotations

from pathlib import Path


from installer.migrations.types import PendingProject
from installer.screens.migration_overview import MigrationOverviewScreen


def _fixture_projects(tmp_path: Path) -> list[PendingProject]:
    return [
        PendingProject(
            name="cpm",
            path=tmp_path / "cpm",
            schema_version_path=tmp_path / "cpm" / ".schema-version",
            current_version=1,
        ),
        PendingProject(
            name="side",
            path=tmp_path / "side",
            schema_version_path=tmp_path / "side" / ".schema-version",
            current_version=1,
        ),
    ]


def test_overview_snapshot(snap_compare, tmp_path: Path) -> None:
    from textual.app import App

    class Harness(App):
        def on_mount(self) -> None:
            self.push_screen(
                MigrationOverviewScreen(
                    pending=_fixture_projects(tmp_path),
                    integration_map={"cpm": {"T", "R", "J"}, "side": {"T"}},
                    counts={"cpm": (12, 38), "side": (4, 9)},
                ),
            )

    assert snap_compare(Harness())


def test_review_screen_snapshot(snap_compare, tmp_path: Path) -> None:
    from textual.app import App

    from installer.migrations.integrations.base import Action
    from installer.migrations.types import (
        MigrationPlan,
        PendingProject,
        RecoveryPath,
        TodoRef,
    )
    from installer.screens.migration_review import MigrationReviewScreen

    project = PendingProject(
        name="cpm",
        path=tmp_path / "cpm",
        schema_version_path=tmp_path / "cpm" / ".schema-version",
        current_version=1,
    )
    plan = MigrationPlan(
        project=project,
        parents=[TodoRef(id="475", title="Review everything")],
        children=[
            TodoRef(id=f"475.{i}", title=f"child {i}", parent="475") for i in range(3)
        ],
        integration_actions={
            "todoist": [
                Action(kind="clear_parent", target_id=f"task-{i}", payload={})
                for i in range(3)
            ],
            "trello": [],
            "jira": [],
        },
        recovery_path=RecoveryPath.NORMAL,
    )

    class Harness(App):
        def on_mount(self) -> None:
            self.push_screen(MigrationReviewScreen(plan=plan, backup_preview="/tmp/b"))

    assert snap_compare(Harness())


def test_review_dry_run_tab_snapshot(snap_compare, tmp_path: Path) -> None:
    from textual.app import App

    from installer.migrations.integrations.base import Action
    from installer.migrations.types import (
        MigrationPlan,
        PendingProject,
        RecoveryPath,
        TodoRef,
    )
    from installer.screens.migration_review import MigrationReviewScreen

    project = PendingProject(
        name="cpm",
        path=tmp_path / "cpm",
        schema_version_path=tmp_path / "cpm" / ".schema-version",
        current_version=1,
    )
    plan = MigrationPlan(
        project=project,
        parents=[TodoRef(id="1", title="p")],
        children=[TodoRef(id="1.1", title="c", parent="1", todoist_task_id="t1")],
        integration_actions={
            "todoist": [Action(kind="clear_parent", target_id="t1", payload={})],
            "trello": [],
            "jira": [],
        },
        recovery_path=RecoveryPath.NORMAL,
    )

    class Harness(App):
        def on_mount(self) -> None:
            screen = MigrationReviewScreen(plan=plan, backup_preview="/tmp/b")
            self.push_screen(screen)

        async def on_ready(self) -> None:
            await self.press("d")  # open dry-run tab

    assert snap_compare(Harness())


def test_progress_summary_snapshot(snap_compare, tmp_path: Path) -> None:
    from textual.app import App

    from installer.screens.migration_progress import (
        MigrationOutcome,
        MigrationProgressScreen,
    )

    outcomes = [
        MigrationOutcome(
            project="cpm", ok=True, resync_partial=False, backup="/tmp/b1"
        ),
        MigrationOutcome(
            project="side",
            ok=False,
            resync_partial=False,
            backup="/tmp/b2",
            error="ALTER failed",
        ),
        MigrationOutcome(
            project="legacy", ok=True, resync_partial=True, backup="/tmp/b3"
        ),
    ]

    class Harness(App):
        def on_mount(self) -> None:
            self.push_screen(MigrationProgressScreen(outcomes=outcomes))

    assert snap_compare(Harness())
