# installer/migrations/orchestrator.py
"""Migration orchestrator — chains v1→v2→v3 per project.

run_migrations_for_project runs each applicable migration phase in order:
  - v1 → v2: FlatTodoMigration (flattens parent/children to group: tags)
  - v2 → v3: SqlOnlyMigration  (moves YAML data to SQLite, deletes YAML files)

If a phase fails, the project stays at its current version and the next
wizard run resumes from the correct starting point.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.integrations.base import IntegrationResync
from installer.migrations.sql_only import SqlOnlyMigration
from installer.migrations.types import MigrationState, PendingProject

log = logging.getLogger(__name__)

SQL_ONLY_TARGET = 3


@dataclass
class RunResult:
    stopped_at: int
    """Schema version the project is at after this run (may be < 3 on failure)."""
    reason: str
    """Human-readable explanation."""


def run_migrations_for_project(
    project: PendingProject,
    run_ts: str,
    backup_root: Path,
    integrations: list[IntegrationResync] | None = None,
    strict_resync: bool = False,
) -> RunResult:
    """Chain v1→v2→v3 migration phases for a single project.

    Returns a RunResult indicating the final schema version reached.
    """
    integrations = integrations or []
    current = project.current_version

    # ── Phase 1: v1 → v2 (flat-todo) ──────────────────────────────────────
    if current <= 1:
        flat = FlatTodoMigration(
            project=project,
            run_ts=run_ts,
            backup_root=backup_root,
            integrations=integrations,
            strict_resync=strict_resync,
        )
        try:
            flat.plan()
            flat.confirm()
            flat.execute_local()
            flat.commit()
        except Exception as exc:
            log.error(
                "%s: flat-todo migration failed: %s", project.name, exc, exc_info=True
            )
            return RunResult(
                stopped_at=project.current_version, reason=f"flat-todo failed: {exc}"
            )

        if flat.state != MigrationState.COMMITTED:
            return RunResult(stopped_at=1, reason="flat-todo migration did not commit")

        # Re-read schema_version from disk before proceeding
        project = project.refreshed()
        current = project.current_version

    # ── Phase 2: v2 → v3 (sql-only) ───────────────────────────────────────
    if current <= 2:
        sql = SqlOnlyMigration(
            project=project,
            run_ts=run_ts,
            backup_root=backup_root,
        )
        try:
            sql.plan()
            sql.confirm()
            sql.execute_local()
            sql.commit()
        except Exception as exc:
            log.error(
                "%s: sql-only migration failed: %s", project.name, exc, exc_info=True
            )
            return RunResult(stopped_at=current, reason=f"sql-only failed: {exc}")

        if sql.state != MigrationState.COMMITTED:
            return RunResult(stopped_at=2, reason="sql-only migration did not commit")

        project = project.refreshed()
        current = project.current_version

    return RunResult(stopped_at=current, reason="complete")
