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
        total = len(projects)
        print(
            f"No projects need migration. All {total} project(s) already at schema v3."
        )
        return 0

    print(f"Migrating {len(pending)} project(s) to schema v3...")
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


def run_dry_run(projects: list[dict]) -> int:
    run_ts = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    pending = list(discover_pending(projects))
    if not pending:
        total = len(projects)
        print(
            f"No projects need migration. All {total} project(s) already at "
            f"schema v3. Dry-run is a no-op."
        )
        return 0
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
        print("\nRun `cpm-install --migrate` in an interactive terminal.")
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
