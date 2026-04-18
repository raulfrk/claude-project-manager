# installer/migrations/sql_only.py
"""SqlOnlyMigration — v2 YAML-hybrid → v3 SQL-only migration runner.

Uses the same MigrationRunner state machine as FlatTodoMigration.
No integration resync needed: flat model + integration IDs already aligned
by the v1→v2 migration (Phase 1).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from installer.migrations.backup import BackupSnapshot
from installer.migrations.base import MigrationRunner
from installer.migrations.detect import bump_schema_version
from installer.migrations.sql_only_transform import migrate_yaml_to_sql
from installer.migrations.types import MigrationPlan, MigrationState, PendingProject

log = logging.getLogger(__name__)

_SQL_ONLY_TARGET = 3


@dataclass
class SqlOnlyMigration(MigrationRunner):
    # Override base fields with defaults — __post_init__ fills from self.project.
    project_name: str = field(default="", init=False)
    project_dir: Path = field(default_factory=Path, init=False)
    project: PendingProject = None  # type: ignore[assignment]
    run_ts: str = ""
    backup_root: Path = Path()
    plan_result: MigrationPlan | None = None
    snapshot: BackupSnapshot | None = None

    def __post_init__(self) -> None:
        self.project_name = self.project.name
        self.project_dir = self.project.path

    # ── public phases ───────────────────────────────────────────────────────

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

        # If no YAML files exist, data is already in SQL — skip backup + flatten.
        if not self._has_yaml_files():
            self.transition(MigrationState.BACKED_UP)
            self.transition(MigrationState.FLATTENED)
            self.transition(MigrationState.RESYNCED)
            return

        try:
            self._backup()
            self.transition(MigrationState.BACKED_UP)
        except Exception:
            self.transition(MigrationState.RESTORING)
            self.transition(MigrationState.FAILED)
            raise

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

    # ── hook impls ──────────────────────────────────────────────────────────

    def _plan(self) -> None:
        yaml_files = [
            name
            for name in ("todos.yaml", "archive.yaml", "decisions.yaml")
            if (self.project.path / name).exists()
        ]
        self.plan_result = MigrationPlan(
            project=self.project,
            integration_actions={},
        )
        log.debug(
            "%s: SqlOnlyMigration plan — yaml_files=%s",
            self.project.name,
            yaml_files,
        )

    def _backup(self) -> None:
        # Use "<name>_v3" as snapshot dir to avoid collision when both
        # FlatTodoMigration and SqlOnlyMigration run in the same backup root+ts.
        self.snapshot = BackupSnapshot.create(
            project=f"{self.project.name}_v3",
            run_ts=self.run_ts,
            source_dir=self.project.path,
            backup_root=self.backup_root,
        )

    def _has_yaml_files(self) -> bool:
        return any(
            (self.project.path / name).exists()
            for name in ("todos.yaml", "archive.yaml", "decisions.yaml")
        )

    def _flatten(self) -> None:
        migrate_yaml_to_sql(self.project.path)

    def _resync(self) -> None:
        # No SaaS coordination needed for v2→v3.
        pass

    def _commit(self) -> None:
        bump_schema_version(self.project.path, _SQL_ONLY_TARGET)

    def _restore(self) -> None:
        self.transition(MigrationState.RESTORING)
        if self.snapshot is not None:
            self.snapshot.restore()
        self.transition(MigrationState.FAILED)
