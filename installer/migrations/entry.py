# installer/migrations/entry.py
from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Sequence

from installer.migrations.detect import discover_pending
from installer.migrations.flat_todo import FlatTodoMigration
from installer.migrations.integrations.base import IntegrationResync
from installer.migrations.integrations.jira import JiraResync
from installer.migrations.integrations.todoist import TodoistResync
from installer.migrations.integrations.trello import TrelloResync
from installer.migrations.lock import LockContention, MigrationLock
from installer.migrations.report import write_dry_run_report
from installer.migrations.types import PendingProject

log = logging.getLogger(__name__)

MIGRATION_ROOT = Path.home() / ".claude" / "migrations"

# Inclusive upper bound for "needs sql-only migration"
_SQL_ONLY_MAX_VERSION = 2


def run_pending_migrations(
    projects: list[dict],
    *,
    interactive: bool,
    strict_resync: bool = False,
    backup_retain_days: int | None = None,
) -> int:
    """Entry point called from wizard hook and standalone CLI.

    Runs full v1→v2→v3 chain via the orchestrator for each pending project.
    Returns exit code: 0 all good, 2 partial failure, 3 user quit.
    """
    run_ts = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    pending = list(discover_pending(projects))
    if not pending:
        log.info("no projects need migration")
        return 0

    lock_path = MIGRATION_ROOT / ".lock"
    try:
        with MigrationLock(lock_path):
            return _run_with_lock(
                pending,
                run_ts=run_ts,
                interactive=interactive,
                strict_resync=strict_resync,
                backup_retain_days=backup_retain_days,
            )
    except LockContention as e:
        print(f"Migration already running: {e}")
        return 2


def run_sql_only_migration(
    projects: list[dict],
    *,
    strict_resync: bool = False,
    backup_retain_days: int | None = None,
) -> int:
    """Run only the v2→v3 SQL-only migration.

    Errors if any project is still at v1 (flat-todo migration must run first).
    Returns exit code: 0 success, 1 v1 projects detected, 2 partial failure.
    """
    from installer.migrations.sql_only import SqlOnlyMigration

    run_ts = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    pending = list(discover_pending(projects))
    if not pending:
        log.info("no projects need sql-only migration")
        return 0

    # Check for v1 projects
    v1_projects = [p for p in pending if p.current_version <= 1]
    if v1_projects:
        names = ", ".join(p.name for p in v1_projects)
        print(
            f"Error: projects still at schema_version 1: {names}. "
            "Run `cpm-install --migrate` first."
        )
        return 1

    backup_root = MIGRATION_ROOT / run_ts
    failures = 0
    for p in pending:
        if p.current_version > _SQL_ONLY_MAX_VERSION:
            log.debug("%s: already at v3, skipping", p.name)
            continue
        runner = SqlOnlyMigration(project=p, run_ts=run_ts, backup_root=backup_root)
        try:
            runner.plan()
            runner.confirm()
            runner.execute_local()
            runner.commit()
            print(f"  {p.name}: migrated to v3")
        except Exception as exc:
            log.error("%s: sql-only migration failed: %s", p.name, exc, exc_info=True)
            print(f"  {p.name}: FAILED — {exc}")
            failures += 1

    if backup_retain_days is not None:
        _prune_old_backups(backup_retain_days)

    return 2 if failures else 0


def run_dry_run(projects: list[dict]) -> int:
    run_ts = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    pending = list(discover_pending(projects))
    integrations = _default_integrations()
    plans = []
    for p in pending:
        runner = FlatTodoMigration(
            project=p,
            run_ts=run_ts,
            backup_root=MIGRATION_ROOT / run_ts,
            integrations=integrations,
        )
        plans.append(runner.plan())
    out_dir = MIGRATION_ROOT / run_ts
    out_dir.mkdir(parents=True, exist_ok=True)
    write_dry_run_report(plans, out_dir / "dry-run.md", run_ts=run_ts)
    print(f"Dry-run report: {out_dir / 'dry-run.md'}")
    return 0


def _run_with_lock(
    pending: Sequence[PendingProject],
    *,
    run_ts: str,
    interactive: bool,
    strict_resync: bool,
    backup_retain_days: int | None,
) -> int:
    if not interactive:
        # Non-TTY mode — print overview and exit with a warning
        print("Flat-todo migration needs an interactive TTY.")
        print("Projects pending:")
        for p in pending:
            print(f"  - {p.name}  (schema_version {p.current_version} → 2)")
        print("\nRun `installer --migrate-flat` in an interactive terminal.")
        return 0

    # Interactive mode: hand off to TUI driver (implemented in Task 18 via app.py hook)
    from installer.app import run_migration_tui

    exit_code = run_migration_tui(
        pending=list(pending),
        run_ts=run_ts,
        integrations=_default_integrations(),
        backup_root=MIGRATION_ROOT / run_ts,
        strict_resync=strict_resync,
    )
    if backup_retain_days is not None:
        _prune_old_backups(backup_retain_days)
    return exit_code


def _default_integrations() -> list[IntegrationResync]:
    return [TodoistResync(), TrelloResync(), JiraResync()]


def _prune_old_backups(days: int) -> None:
    cutoff = dt.datetime.now() - dt.timedelta(days=days)
    if not MIGRATION_ROOT.exists():
        return
    for child in MIGRATION_ROOT.iterdir():
        if not child.is_dir():
            continue
        try:
            ts = dt.datetime.strptime(child.name, "%Y-%m-%dT%H-%M-%S")
        except ValueError:
            continue
        if ts < cutoff:
            import shutil

            shutil.rmtree(child)
