# installer/migrations/flat_todo.py
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from installer.migrations.backup import BackupSnapshot
from installer.migrations.base import MigrationRunner
from installer.migrations.detect import bump_schema_version, detect_already_flat
from installer.migrations.integrations.base import FailedAction, IntegrationResync
from installer.migrations.transform import flatten_todos_sql, flatten_todos_yaml
from installer.migrations.types import (
    MigrationPlan,
    MigrationState,
    PendingProject,
    RecoveryPath,
    TodoRef,
)

# FlatTodoMigration bumps v1 → v2 only; SqlOnlyMigration handles v2 → v3
_FLAT_TODO_TARGET = 2

log = logging.getLogger(__name__)


class ResyncFailure(RuntimeError):
    """Raised when --strict-resync is set and any integration reports a failure."""


@dataclass
class FlatTodoMigration(MigrationRunner):
    # Override base fields with defaults so callers don't need to pass them;
    # __post_init__ fills them from self.project.
    project_name: str = field(default="", init=False)
    project_dir: Path = field(default_factory=Path, init=False)
    project: PendingProject = None  # type: ignore[assignment]
    run_ts: str = ""
    backup_root: Path = Path()
    integrations: list[IntegrationResync] = field(default_factory=list)
    strict_resync: bool = False
    plan_result: MigrationPlan | None = None
    snapshot: BackupSnapshot | None = None
    resync_failures: list[FailedAction] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Populate base-class fields from project
        self.project_name = self.project.name
        self.project_dir = self.project.path

    # --- public phases ---------------------------------------------------

    def plan(self) -> MigrationPlan:
        self._plan()
        self.transition(MigrationState.PLANNED)
        assert self.plan_result is not None
        return self.plan_result

    def confirm(self, confirmed: bool = True) -> None:
        self.transition(
            MigrationState.CONFIRMED if confirmed else MigrationState.SKIPPED
        )

    def execute_local(self) -> None:
        if self.plan_result is None:
            raise RuntimeError("plan() must run before execute_local()")
        try:
            self._backup()
            self.transition(MigrationState.BACKED_UP)
        except Exception:
            self.transition(MigrationState.RESTORING)
            self.transition(MigrationState.FAILED)
            raise

        if self.plan_result.recovery_path == RecoveryPath.BUMP_ONLY:
            # Skip flatten entirely
            self.transition(MigrationState.FLATTENED)
            self.transition(MigrationState.RESYNCED)
            return

        try:
            self._flatten()
            self.transition(MigrationState.FLATTENED)
            self._resync()
            self.transition(MigrationState.RESYNCED)
        except Exception:
            self._restore()
            raise

    def commit(self) -> None:
        try:
            self._commit()
            self.transition(MigrationState.COMMITTED)
        except Exception:
            self._restore()
            raise

    # --- hook impls ------------------------------------------------------

    def _plan(self) -> None:
        todos_path = self.project.path / "todos.yaml"
        data = yaml.safe_load(todos_path.read_text()) or []
        parents: list[TodoRef] = []
        children: list[TodoRef] = []
        migrated: list[TodoRef] = []
        for t in data:
            ref = TodoRef(
                id=t.get("id", ""),
                title=t.get("title", ""),
                todoist_task_id=t.get("todoist_task_id"),
                trello_card_id=t.get("trello_card_id"),
                trello_checklist_id=t.get("trello_checklist_id"),
                trello_checklist_item_id=t.get("trello_checklist_item_id"),
                jira_issue_key=t.get("jira_issue_key"),
                parent=t.get("parent"),
            )
            migrated.append(ref)
            if t.get("children"):
                parents.append(ref)
            if t.get("parent") is not None:
                children.append(ref)
        recovery = (
            RecoveryPath.BUMP_ONLY
            if detect_already_flat(todos_path)
            else RecoveryPath.NORMAL
        )

        integration_actions: dict[str, list] = {}
        for integ in self.integrations:
            if not integ.enabled_for(self.project):
                continue
            integration_actions[integ.name] = integ.plan(self.project, migrated)

        self.plan_result = MigrationPlan(
            project=self.project,
            parents=parents,
            children=children,
            integration_actions=integration_actions,
            recovery_path=recovery,
        )

    def _backup(self) -> None:
        self.snapshot = BackupSnapshot.create(
            project=self.project.name,
            run_ts=self.run_ts,
            source_dir=self.project.path,
            backup_root=self.backup_root,
        )

    def _flatten(self) -> None:
        flatten_todos_yaml(self.project.path / "todos.yaml")
        archive = self.project.path / "archive.yaml"
        if archive.exists():
            flatten_todos_yaml(archive)
        flatten_todos_sql(self.project.path / "data.db")

    def _resync(self) -> None:
        assert self.plan_result is not None
        for integ in self.integrations:
            if not integ.enabled_for(self.project):
                continue
            actions = self.plan_result.integration_actions.get(integ.name, [])
            result = integ.execute(self.project, actions)
            self.resync_failures.extend(result.failed)
            if result.aborted:
                log.warning(
                    "%s: integration %s aborted; continuing with remaining integrations",
                    self.project.name,
                    integ.name,
                )
            if self.strict_resync and (result.failed or result.aborted):
                raise ResyncFailure(
                    f"{self.project.name}: strict resync: {integ.name} reported "
                    f"{len(result.failed)} failures (aborted={result.aborted})",
                )

    def _commit(self) -> None:
        bump_schema_version(self.project.path, _FLAT_TODO_TARGET)

    def _restore(self) -> None:
        self.transition(MigrationState.RESTORING)
        if self.snapshot is not None:
            self.snapshot.restore()
        self.transition(MigrationState.FAILED)
