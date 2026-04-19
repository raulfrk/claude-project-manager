"""Migration TUI helpers for the installer."""

from __future__ import annotations

import dataclasses
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger("installer.app")


def _run_sql_phase(
    project: "PendingProject",  # noqa: F821
    run_ts: str,
    backup_root: "Path",  # noqa: F821
) -> "tuple[bool, str | None]":
    """Run SqlOnlyMigration for a project already at v2. Returns (ok, error).

    Unattended — no user review. The sql phase is deterministic (moves YAML to
    SQLite, deletes YAML files) so no per-project confirmation is needed.
    """
    from installer.migrations.sql_only import SqlOnlyMigration

    if project.current_version >= 3:
        return True, None
    if project.current_version < 2:
        return False, f"expected v2 or later, got v{project.current_version}"

    runner = SqlOnlyMigration(project=project, run_ts=run_ts, backup_root=backup_root)
    try:
        runner.plan()
        runner.confirm()
        runner.execute_local()
        runner.commit()
    except Exception as exc:
        import logging

        logging.getLogger(__name__).error(
            "%s: sql-only migration failed: %s", project.name, exc, exc_info=True
        )
        return False, str(exc)
    return True, None


def run_migration_tui(
    *,
    pending: list,
    run_ts: str,
    integrations: list,
    backup_root: "Path",  # noqa: F821
    strict_resync: bool,
) -> int:
    """Drive the migration flow via Rich prompts.

    Returns exit code: 0 success, 2 partial, 3 user quit.
    """

    from installer.flow.console import get_console
    from installer.flow.migration_flow import (
        prompt_migration_action,
        prompt_migration_review,
    )
    from installer.flow.migration_summary import (
        MigrationOutcome,
        show_migration_summary,
    )
    from installer.migrations.flat_todo import FlatTodoMigration

    outcomes: list[MigrationOutcome] = []
    _collected_runners: list[FlatTodoMigration] = []
    exit_code = 0

    console = get_console()

    # Overview: let user decide to review, skip-all, or quit.
    action = prompt_migration_action(
        pending=list(pending),
        integration_map=_integration_badges(pending, integrations),
        counts={p.name: _count_parents_children(p) for p in pending},
        console=console,
    )
    if action == "quit":
        return 3
    if action == "skip_all":
        show_migration_summary([], console)
        return 0

    # Per-project loop.
    for project in pending:
        # Already at v2+: skip flat review, run sql-only phase unattended.
        if project.current_version >= 2:
            ok, err = _run_sql_phase(project, run_ts, backup_root)
            outcomes.append(
                MigrationOutcome(
                    project=project.name,
                    ok=ok,
                    resync_partial=False,
                    backup=str(backup_root / project.name),
                    error=err,
                )
            )
            _collected_runners.append(
                None
            )  # keep zip(outcomes, _collected_runners) aligned
            if not ok:
                exit_code = max(exit_code, 2)
            continue

        runner = FlatTodoMigration(
            project=project,
            run_ts=run_ts,
            backup_root=backup_root,
            integrations=integrations,
            strict_resync=strict_resync,
        )
        plan = runner.plan()

        review_action = prompt_migration_review(
            plan=plan,
            backup_preview=str(backup_root / project.name),
            console=console,
        )

        if review_action == "quit":
            runner.confirm(False)
            exit_code = max(exit_code, 3)
            break

        if review_action == "skip":
            runner.confirm(False)
            outcomes.append(
                MigrationOutcome(
                    project=runner.project.name,
                    ok=True,
                    resync_partial=False,
                    backup="—",
                ),
            )
            # Do NOT append to _collected_runners for skips — zip() truncates to
            # shorter list, so skipped projects are excluded from errors.log/runbooks.
            continue

        # review_action == "migrate"
        runner.confirm(True)
        try:
            runner.execute_local()
            runner.commit()
            partial = bool(runner.resync_failures)
            outcomes.append(
                MigrationOutcome(
                    project=runner.project.name,
                    ok=True,
                    resync_partial=partial,
                    backup=str(runner.snapshot.dir) if runner.snapshot else "—",
                ),
            )
            _collected_runners.append(runner)
            if partial:
                exit_code = max(exit_code, 2)

            # Chain sql-only phase: flat commit → project now at v2 → run v2→v3.
            refreshed = runner.project.refreshed()
            sql_ok, sql_err = _run_sql_phase(refreshed, run_ts, backup_root)
            if not sql_ok:
                exit_code = max(exit_code, 2)
                # Mutate the outcome entry in place to carry the sql-phase error.
                outcomes[-1] = dataclasses.replace(
                    outcomes[-1],
                    ok=False,
                    error=f"sql-phase failed: {sql_err}",
                )
        except Exception as e:
            outcomes.append(
                MigrationOutcome(
                    project=runner.project.name,
                    ok=False,
                    resync_partial=False,
                    backup=str(runner.snapshot.dir) if runner.snapshot else "—",
                    error=str(e),
                ),
            )
            _collected_runners.append(runner)
            exit_code = max(exit_code, 2)

    show_migration_summary(outcomes, console)

    # Write consolidated JSONL errors log
    errors_path = backup_root / "errors.log"
    errors_path.parent.mkdir(parents=True, exist_ok=True)
    with errors_path.open("w") as f:
        for outcome, runner in zip(outcomes, _collected_runners):
            for fail in getattr(runner, "resync_failures", []):
                f.write(
                    json.dumps(
                        {
                            "ts": run_ts,
                            "project": outcome.project,
                            "phase": f"resync:{fail.action.kind}",
                            "action_id": fail.action.target_id,
                            "error_class": fail.error_class,
                            "message": fail.message,
                            "retryable": fail.retryable,
                        }
                    )
                    + "\n",
                )

    _emit_resync_runbooks(_collected_runners, outcomes)
    return exit_code


def _emit_resync_runbooks(
    collected_runners: list,
    outcomes: list,
    stream=None,
) -> None:
    """Print a user-visible runbook after migration when any runner had a
    Todoist api_token-missing failure. Silent otherwise.

    Called after MigrationApp exits so stdout/stderr reach the terminal.
    """
    if stream is None:
        stream = sys.stderr

    affected_projects: list[str] = []
    for outcome, runner in zip(outcomes, collected_runners):
        failures = getattr(runner, "resync_failures", [])
        if any("api_token not found" in fail.message for fail in failures):
            affected_projects.append(outcome.project)

    if not affected_projects:
        return

    print(
        "\n⚠ Todoist resync skipped — api_token not found in "
        "~/.claude/todoist.yaml or proj.yaml.",
        file=stream,
    )
    print(
        "  Run `/proj:todoist-sync` on each affected project to push "
        "the flat structure to Todoist:",
        file=stream,
    )
    for name in affected_projects:
        print(f"    - {name}", file=stream)


def _unwrap_todos(raw: object) -> list[dict]:
    """Real proj-plugin todos.yaml uses `{"todos": [...]}` wrapper; bare list accepted."""
    if isinstance(raw, dict):
        data = raw.get("todos") or raw.get("items") or []
    elif isinstance(raw, list):
        data = raw
    else:
        return []
    return [t for t in data if isinstance(t, dict)]


def _integration_badges(pending, integrations) -> dict[str, set[str]]:
    """Compute the letter badge set per project based on live integration links."""
    import yaml

    badges: dict[str, set[str]] = {}
    for project in pending:
        s: set[str] = set()
        todos_path = project.path / "todos.yaml"
        if todos_path.exists():
            todos = _unwrap_todos(yaml.safe_load(todos_path.read_text()))
            for t in todos:
                if t.get("todoist_task_id"):
                    s.add("T")
                if t.get("trello_card_id") or t.get("trello_checklist_item_id"):
                    s.add("R")
                if t.get("jira_issue_key"):
                    s.add("J")
        badges[project.name] = s
    return badges


def _count_parents_children(project) -> tuple[int, int]:
    import yaml

    todos_path = project.path / "todos.yaml"
    if not todos_path.exists():
        return 0, 0
    todos = _unwrap_todos(yaml.safe_load(todos_path.read_text()))
    parents = sum(1 for t in todos if t.get("children"))
    children = sum(1 for t in todos if t.get("parent") is not None)
    return parents, children
