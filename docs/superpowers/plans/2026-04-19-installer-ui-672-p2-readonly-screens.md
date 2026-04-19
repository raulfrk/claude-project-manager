# Installer UI Migration — Phase 2: Summary Deletion + Migration Overview/Review → Rich

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Delete orphaned `installer/screens/summary.py` (SummaryScreen — dead code after P1 restructure moved install-outcome display to `main.py`). Port `installer/screens/migration_overview.py` + `installer/screens/migration_review.py` to Rich-based functions in `installer/flow/`. Restructure `run_migration_tui` in `installer/app.py` to not use a nested Textual `MigrationApp` for these two screens.

**Architecture:**
- SummaryScreen: confirmed dead code. Only reference is its own test. Pure deletion — no port needed.
- Migration overview: Rich Panel + Table + `Prompt.ask(choices=["r", "s", "q"])` in `installer/flow/migration_flow.py::prompt_migration_action`.
- Migration review: Rich Panel + `Prompt.ask(choices=["m", "s", "d", "q"])`, with a dry-run sub-prompt that shows Rich Panel + `Prompt.ask()` to close.
- `run_migration_tui` becomes a plain-Python function that loops over projects, calling these Rich prompts per project. Nested `MigrationApp` class deleted.

**Tech Stack:** Python 3.13, Rich 13+ (`rich.prompt.Prompt`, `rich.panel.Panel`, `rich.table.Table`), pytest, syrupy.

**Spec:** `docs/superpowers/specs/2026-04-19-installer-ui-framework-migration-design.md`

**Latent bugs addressed this phase:** none (the P2 row in spec lists no latent bugs).

---

## File Structure

**Created:**
- `installer/flow/migration_flow.py` — `prompt_migration_action(pending, integration_map, counts, console) -> Literal["review", "skip_all", "quit"]` + `prompt_migration_review(plan, backup_preview, console) -> Literal["migrate", "skip", "quit"]` + `show_dry_run_preview(plan, console)` helper.
- `installer/tests/flow/test_migration_flow.py` — unit tests for each function (mock Rich Prompt via `monkeypatch.setattr("rich.prompt.Prompt.ask", ...)`).

**Modified:**
- `installer/app.py::run_migration_tui` — replace nested `MigrationApp(App)` class + its screen pushes with a plain `for project in pending:` loop that calls the new flow functions. The function stops being a Textual-hosted driver. Delete the inner `class MigrationApp`, `_after_overview`, `_review_next`, `_after_review` methods. Keep the per-project migration logic (`runner.plan()` → confirm → `runner.execute_local()` → `runner.commit()` → sql-phase).

**Deleted (at end of phase):**
- `installer/screens/summary.py` + `installer/tests/test_summary_screen.py` — orphan dead code.
- `installer/screens/migration_overview.py` + `installer/screens/migration_review.py` — ported.
- `installer/tests/migrations/test_screens.py::test_overview_snapshot`, `test_review_screen_snapshot`, `test_review_dry_run_tab_snapshot` — Textual-specific snapshot tests covering the deleted screens. If `test_screens.py` has other tests worth keeping, preserve them; otherwise delete the file.
- Related Textual SVG goldens (search under `installer/tests/migrations/__snapshots__/`).
- Exports in `installer/screens/__init__.py` for deleted classes.

---

## Task 1: Delete dead SummaryScreen + its test

**Files:**
- Delete: `installer/screens/summary.py`
- Delete: `installer/tests/test_summary_screen.py`
- Modify: `installer/screens/__init__.py` — remove SummaryScreen + PluginOutcome exports.

**Context:** Post-P1, SummaryScreen has zero runtime callers. The `_on_progress_done` callback that used to push it was deleted in ac3d622. Pure deletion.

- [ ] **Step 1: Confirm no runtime references**

```bash
cd /home/raul/worktrees/cpm/feat-672-p2-readonly-screens
grep -rn "SummaryScreen\|PluginOutcome" installer/ --include='*.py'
```

Expected: only hits inside `installer/screens/summary.py`, `installer/tests/test_summary_screen.py`, and the import line in `installer/screens/__init__.py`. If anything else references them, STOP and report — P1 missed a site.

- [ ] **Step 2: Delete the files**

```bash
rm installer/screens/summary.py installer/tests/test_summary_screen.py
```

- [ ] **Step 3: Remove from `installer/screens/__init__.py`**

Read the file, then remove:
- `from installer.screens.summary import SummaryScreen, PluginOutcome` (or whichever line imports them)
- `"SummaryScreen",` and `"PluginOutcome",` entries in `__all__`

- [ ] **Step 4: Run installer tests**

```bash
cd installer && uv run pytest tests/ --no-cov -q 2>&1 | tail -10
```

Expected: tests pass (modulo pre-existing unrelated snapshot flakes on wizard/plugin_select).

- [ ] **Step 5: Grep hygiene**

```bash
grep -rn "SummaryScreen\|PluginOutcome" /home/raul/worktrees/cpm/feat-672-p2-readonly-screens/installer/ --include='*.py'
```

Expected: zero hits.

- [ ] **Step 6: Commit**

```bash
git add -A installer/
git commit -m "chore(installer/672): delete orphan SummaryScreen + PluginOutcome (P2)

P1 restructure moved install-outcome display to main.py's failure loop;
SummaryScreen became dead code. Only reference was its own test file.
Pure deletion."
```

---

## Task 2: Port MigrationOverviewScreen → `prompt_migration_action`

**Files:**
- Create: `installer/flow/migration_flow.py`
- Create: `installer/tests/flow/test_migration_flow.py`

- [ ] **Step 1: Write the failing test**

Create `installer/tests/flow/test_migration_flow.py`:

```python
# installer/tests/flow/test_migration_flow.py
from pathlib import Path

import pytest
from rich.console import Console

from installer.flow.migration_flow import prompt_migration_action
from installer.migrations.types import PendingProject


def _p(name: str) -> PendingProject:
    return PendingProject(
        name=name,
        path=Path("/tmp") / name,
        schema_version_path=Path("/tmp") / name / ".schema-version",
        current_version=1,
    )


class TestPromptMigrationAction:
    def test_review_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "r")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = prompt_migration_action(
            pending=[_p("alpha"), _p("beta")],
            integration_map={"alpha": {"todoist"}, "beta": set()},
            counts={"alpha": (2, 3), "beta": (0, 0)},
            console=console,
        )
        assert result == "review"

    def test_skip_all_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "s")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = prompt_migration_action(
            pending=[_p("alpha")],
            integration_map={"alpha": set()},
            counts={"alpha": (1, 0)},
            console=console,
        )
        assert result == "skip_all"

    def test_quit_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "q")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = prompt_migration_action(
            pending=[_p("alpha")],
            integration_map={"alpha": set()},
            counts={"alpha": (1, 0)},
            console=console,
        )
        assert result == "quit"

    def test_table_rendered_with_project_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "q")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        prompt_migration_action(
            pending=[_p("alpha"), _p("beta")],
            integration_map={"alpha": {"todoist", "trello"}, "beta": set()},
            counts={"alpha": (2, 3), "beta": (0, 0)},
            console=console,
        )
        text = console.export_text()
        assert "alpha" in text
        assert "beta" in text
        assert "2" in text  # parents
        assert "3" in text  # children
        assert "todoist" in text or "trello" in text
```

- [ ] **Step 2: Run — expect FAIL**

```bash
cd installer && uv run pytest tests/flow/test_migration_flow.py -v
```

Expected: `ModuleNotFoundError: installer.flow.migration_flow`.

- [ ] **Step 3: Implement `prompt_migration_action`**

Create `installer/flow/migration_flow.py`:

```python
# installer/flow/migration_flow.py
"""Rich-based prompts for the migration flow.

Replaces:
  - MigrationOverviewScreen (deleted P2) → prompt_migration_action
  - MigrationReviewScreen   (deleted P2) → prompt_migration_review
  - DryRunPreviewScreen     (deleted P2) → show_dry_run_preview
"""

from __future__ import annotations

from typing import Literal

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table

from installer.migrations.types import PendingProject


OverviewAction = Literal["review", "skip_all", "quit"]


def prompt_migration_action(
    pending: list[PendingProject],
    integration_map: dict[str, set[str]],
    counts: dict[str, tuple[int, int]],
    console: Console,
) -> OverviewAction:
    """Display project list + prompt for r/s/q.

    Returns one of ``"review"`` / ``"skip_all"`` / ``"quit"``.
    """
    console.print(
        f"[bold]{len(pending)} projects need migration to schema_version=2.[/]"
    )
    table = Table(show_header=True, header_style="bold")
    table.add_column("Project")
    table.add_column("Parents")
    table.add_column("Children")
    table.add_column("Remote")
    for p in pending:
        parents, children = counts.get(p.name, (0, 0))
        remote = ",".join(sorted(integration_map.get(p.name, set()))) or "–"
        table.add_row(p.name, str(parents), str(children), remote)
    console.print(table)
    console.print(
        "[dim]r[/]=review + migrate   [dim]s[/]=skip all   [dim]q[/]=quit"
    )

    choice = Prompt.ask("Action", choices=["r", "s", "q"], default="r", console=console)
    return {"r": "review", "s": "skip_all", "q": "quit"}[choice]
```

- [ ] **Step 4: Run — expect 4 PASS**

```bash
cd installer && uv run pytest tests/flow/test_migration_flow.py -v
```

- [ ] **Step 5: Commit**

```bash
git add installer/flow/migration_flow.py installer/tests/flow/test_migration_flow.py
git commit -m "feat(installer/672): port MigrationOverviewScreen → flow.prompt_migration_action (P2)"
```

---

## Task 3: Port MigrationReviewScreen → `prompt_migration_review` + `show_dry_run_preview`

**Files:**
- Modify: `installer/flow/migration_flow.py` — add two new functions.
- Modify: `installer/tests/flow/test_migration_flow.py` — add tests.

- [ ] **Step 1: Append failing tests**

Append to `installer/tests/flow/test_migration_flow.py`:

```python
from installer.flow.migration_flow import prompt_migration_review, show_dry_run_preview
from installer.migrations.types import MigrationPlan, TodoRef


def _make_plan() -> MigrationPlan:
    parent = TodoRef(id="1", title="parent")
    c1 = TodoRef(id="1.1", title="c1", parent="1")
    c2 = TodoRef(id="1.2", title="c2", parent="1")
    return MigrationPlan(
        project=_p("alpha"),
        parents=[parent],
        children=[c1, c2],
        integration_actions={"todoist": [], "trello": []},
    )


class TestPromptMigrationReview:
    def test_migrate_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # First prompt -> 'm', confirm dialog -> 'y'.
        calls = iter(["m", "y"])
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: next(calls))
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = prompt_migration_review(
            plan=_make_plan(),
            backup_preview="/tmp/backup/alpha",
            console=console,
        )
        assert result == "migrate"

    def test_migrate_declined_maps_to_skip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = iter(["m", "n"])
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: next(calls))
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = prompt_migration_review(
            plan=_make_plan(),
            backup_preview="/tmp/backup/alpha",
            console=console,
        )
        assert result == "skip"

    def test_skip_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "s")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert (
            prompt_migration_review(
                plan=_make_plan(), backup_preview="/tmp/bk/alpha", console=console
            )
            == "skip"
        )

    def test_quit_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "q")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert (
            prompt_migration_review(
                plan=_make_plan(), backup_preview="/tmp/bk/alpha", console=console
            )
            == "quit"
        )

    def test_dry_run_then_migrate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # First prompt -> 'd' (dry-run), then any key to close preview,
        # then 'm' at the main prompt again, then 'y' at confirm.
        calls = iter(["d", "", "m", "y"])
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: next(calls))
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = prompt_migration_review(
            plan=_make_plan(),
            backup_preview="/tmp/bk/alpha",
            console=console,
        )
        assert result == "migrate"


class TestShowDryRunPreview:
    def test_renders_plan(self) -> None:
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        show_dry_run_preview(_make_plan(), console)
        text = console.export_text()
        assert "children" in text.lower() or "1.1" in text
        assert "todoist" in text.lower() or "trello" in text.lower()
```

- [ ] **Step 2: Run — expect FAIL (ImportError)**

- [ ] **Step 3: Implement the two functions**

Append to `installer/flow/migration_flow.py`:

```python
from installer.migrations.types import MigrationPlan


ReviewAction = Literal["migrate", "skip", "quit"]


def show_dry_run_preview(plan: MigrationPlan, console: Console) -> None:
    """Print the dry-run preview (local diff sample + remote actions)."""
    console.print("[bold]Dry-run preview[/]")
    console.print("[bold]Local diff (sample of first 3 children):[/]")
    for c in plan.children[:3]:
        console.print(
            f"  - id={c.id}  parent={c.parent}  → tags+=group:{c.parent}"
        )
    console.print()
    console.print("[bold]Remote actions:[/]")
    for integ, actions in plan.integration_actions.items():
        console.print(f"  [bold]{integ}[/] ({len(actions)} actions)")
        for a in actions[:20]:
            console.print(f"    • {a.kind}  target={a.target_id}")
        if len(actions) > 20:
            console.print(f"    … {len(actions) - 20} more")


def prompt_migration_review(
    plan: MigrationPlan, backup_preview: str, console: Console
) -> ReviewAction:
    """Render review panel + prompt for m/s/d/q. Loops on 'd' (dry-run).

    Returns one of ``"migrate"`` / ``"skip"`` / ``"quit"``. A ``"migrate"``
    response is gated by a y/n confirm prompt; ``"n"`` maps to ``"skip"``.
    """
    while True:
        console.print()
        console.print(f"[bold]Plan preview — {plan.project.name}[/]")
        console.print(
            f"  • {len(plan.parents)} parent todos → flat with group:<id>"
        )
        console.print(
            f"  • {len(plan.children)} children → top-level with group:<parent>"
        )
        console.print("  • No parent/children fields after migration")
        totals = {k: len(v) for k, v in plan.integration_actions.items()}
        console.print(
            f"[bold]Remote resync[/]  Todoist: {totals.get('todoist', 0)}  "
            f"Trello: {totals.get('trello', 0)}  Jira: {totals.get('jira', 0)}"
        )
        console.print(f"[bold]Backup:[/] {backup_preview}")
        console.print(
            "[dim]m[/]=migrate  [dim]s[/]=skip  [dim]d[/]=dry-run preview  [dim]q[/]=quit"
        )

        choice = Prompt.ask(
            "Action", choices=["m", "s", "d", "q"], default="m", console=console
        )
        if choice == "d":
            show_dry_run_preview(plan, console)
            Prompt.ask("Press Enter to return", console=console)
            continue

        if choice == "m":
            total_actions = sum(len(v) for v in plan.integration_actions.values())
            confirm = Prompt.ask(
                f"Proceed with {total_actions} remote actions across "
                f"{len(plan.integration_actions)} integrations?",
                choices=["y", "n"],
                default="y",
                console=console,
            )
            return "migrate" if confirm == "y" else "skip"
        if choice == "s":
            return "skip"
        if choice == "q":
            return "quit"
```

- [ ] **Step 4: Run — expect PASS**

```bash
cd installer && uv run pytest tests/flow/test_migration_flow.py -v
```

Expected: all 9 tests pass (4 overview + 5 review/dry-run).

- [ ] **Step 5: Commit**

```bash
git add installer/flow/migration_flow.py installer/tests/flow/test_migration_flow.py
git commit -m "feat(installer/672): port MigrationReviewScreen + DryRunPreviewScreen → flow (P2)"
```

---

## Task 4: Restructure `run_migration_tui` — drop the nested Textual `MigrationApp`

**File:** `installer/app.py::run_migration_tui` (lines 688-1105 approximately).

**Context:** The function currently hosts a nested `class MigrationApp(App):` that pushes `MigrationOverviewScreen` + `MigrationReviewScreen` + calls `_run_sql_phase` per project. Replace the nested Textual app with a plain Python loop that calls the new `flow.migration_flow` prompts.

- [ ] **Step 1: Read the current `run_migration_tui`**

```bash
cd /home/raul/worktrees/cpm/feat-672-p2-readonly-screens
sed -n '688,1110p' installer/app.py
```

Identify:
- Top-level variables (`outcomes`, `_collected_runners`, `exit_code`).
- `_after_overview` (dispatches on overview action).
- `_review_next` (loops over `pending`, handles v2+ skip, builds `FlatTodoMigration` runner + pushes review screen).
- `_after_review` (dispatches on review action, runs local migration + sql phase, stores outcome).
- Post-loop: `show_migration_summary(outcomes, get_console())`, `return exit_code`.

- [ ] **Step 2: Replace the nested `MigrationApp` with a plain function**

Replace lines 705-1081 (the `class MigrationApp(App):` block + `MigrationApp().run()` call) with:

```python
    # Sequential flow — no Textual app. Each project is prompted via Rich.
    from installer.flow.console import get_console
    from installer.flow.migration_flow import (
        prompt_migration_action,
        prompt_migration_review,
    )

    console = get_console()

    action = prompt_migration_action(
        pending=pending,
        integration_map=_integration_badges(pending, integrations),
        counts={p.name: _count_parents_children(p) for p in pending},
        console=console,
    )
    if action == "quit":
        return 3
    if action == "skip_all":
        # No outcomes to show.
        show_migration_summary([], console)
        return 0

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
            _collected_runners.append(None)
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
                    project=project.name,
                    ok=False,
                    resync_partial=False,
                    backup="–",
                    error="user skipped",
                )
            )
            _collected_runners.append(None)
            continue

        # review_action == "migrate"
        runner.confirm(True)
        try:
            runner.execute_local()
            runner.commit()
            # Run SQL phase now that the runner has committed the flat yaml.
            sql_ok, sql_err = _run_sql_phase(project, run_ts, backup_root)
            if not sql_ok:
                exit_code = max(exit_code, 2)
                outcomes.append(
                    dataclasses.replace(
                        _make_outcome_from_runner(runner, project, backup_root),
                        ok=False,
                        error=f"sql-phase failed: {sql_err}",
                    )
                )
            else:
                outcomes.append(
                    _make_outcome_from_runner(runner, project, backup_root)
                )
        except Exception as e:
            exit_code = max(exit_code, 2)
            outcomes.append(
                MigrationOutcome(
                    project=project.name,
                    ok=False,
                    resync_partial=False,
                    backup=str(backup_root / project.name),
                    error=f"migration failed: {e}",
                )
            )
        _collected_runners.append(runner)

    # Post-loop: errors.log + summary (moved from old MigrationApp._review_next exit).
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
    show_migration_summary(outcomes, console)
    return exit_code
```

Extract the `_make_outcome_from_runner` helper if it doesn't exist (search for how the original `_after_review` constructed the `MigrationOutcome` — copy that logic into a local helper or inline it).

**Remove unused imports** at the top of `run_migration_tui`:
- `from installer.screens.migration_overview import MigrationOverviewScreen` — DELETE
- `from installer.screens.migration_review import MigrationReviewScreen` — DELETE
- `from textual.app import App` — delete ONLY if no other code in the function references `App` (shouldn't).

Keep: `MigrationOutcome`, `show_migration_summary`, `get_console`, `FlatTodoMigration`, `json`, `dataclasses` (for `dataclasses.replace`).

- [ ] **Step 3: Run migration e2e + unit tests**

```bash
cd installer && uv run pytest tests/migrations/ tests/flow/ --no-cov -q 2>&1 | tail -15
```

Expected: all pass. The migration e2e tests that used to assert Textual screens being pushed will need adjustment — if any e2e test calls `run_migration_tui()` and expects a Textual flow, update it to monkeypatch `prompt_migration_action` + `prompt_migration_review` instead.

If any migration e2e test drives the Textual app via `pilot.press(...)`, STOP and report BLOCKED — those tests need rewriting, which is bigger than this task's scope. Defer to a follow-up or break this task.

- [ ] **Step 4: Commit**

```bash
git add installer/app.py installer/tests/  # (any test updates)
git commit -m "refactor(installer/672): run_migration_tui uses Rich flow prompts, drop nested MigrationApp (P2)

Deletes the nested Textual MigrationApp class in run_migration_tui;
replaces it with a plain-Python loop that calls
flow.migration_flow.prompt_migration_action + prompt_migration_review.
Preserves all per-project behavior (v2+ skip-to-sql, runner lifecycle,
errors.log, summary, resync runbooks).

Part of #672 Phase 2."
```

---

## Task 5: Delete migration_overview.py + migration_review.py + Textual tests

**Files:**
- Delete: `installer/screens/migration_overview.py`
- Delete: `installer/screens/migration_review.py`
- Delete: specific tests in `installer/tests/migrations/test_screens.py` (overview + review + dry_run_tab snapshot tests)
- Delete: SVG goldens matching those tests
- Modify: `installer/screens/__init__.py` — remove exports

- [ ] **Step 1: Confirm no runtime references**

```bash
cd /home/raul/worktrees/cpm/feat-672-p2-readonly-screens
grep -rn "MigrationOverviewScreen\|MigrationReviewScreen\|DryRunPreviewScreen\|ConfirmDialog" installer/ --include='*.py'
```

Expected hits ONLY in files to be deleted (`migration_overview.py`, `migration_review.py`, `installer/screens/__init__.py`, `installer/tests/migrations/test_screens.py`). If anything else references them, STOP.

- [ ] **Step 2: Delete the screen files**

```bash
rm installer/screens/migration_overview.py installer/screens/migration_review.py
```

- [ ] **Step 3: Edit `installer/tests/migrations/test_screens.py`**

Delete the three Textual-specific snapshot tests:
- `test_overview_snapshot`
- `test_review_screen_snapshot`
- `test_review_dry_run_tab_snapshot`

If that's all the tests in the file, delete the file + its `__snapshots__/test_screens/` directory. If other tests remain, preserve them + their goldens.

```bash
# if deleting whole file:
rm installer/tests/migrations/test_screens.py
rm -rf installer/tests/migrations/__snapshots__/test_screens/
```

- [ ] **Step 4: Remove exports from `installer/screens/__init__.py`**

```bash
grep -n "migration_overview\|migration_review" installer/screens/__init__.py
```

Remove those import + `__all__` lines.

- [ ] **Step 5: Run full installer test suite**

```bash
cd installer && uv run pytest tests/ --no-cov -q 2>&1 | tail -15
```

Expected: new flow tests pass, migration e2e tests pass, only pre-existing unrelated snapshot flakes remain.

- [ ] **Step 6: Grep hygiene**

```bash
grep -rn "MigrationOverviewScreen\|MigrationReviewScreen\|DryRunPreviewScreen\|ConfirmDialog\|from installer.screens.migration_overview\|from installer.screens.migration_review" /home/raul/worktrees/cpm/feat-672-p2-readonly-screens/installer/ --include='*.py'
```

Expected: zero hits.

- [ ] **Step 7: Commit**

```bash
git add -A installer/
git commit -m "chore(installer/672): delete migration_overview + migration_review Textual screens + snapshot tests (P2)"
```

---

## Task 6: Update screen-inventory docstring in `test_snapshots.py`

- [ ] **Step 1: Edit docstring**

Open `installer/tests/e2e/test_snapshots.py`. In the NOTE paragraph at the top, append:

```
NOTE (2026-04-19, #672 phase 1): ProgressScreen removed — replaced by
installer/flow/install_plan.py::execute_install_plan which uses Rich.
Subsequent phases (P2-P7) will remove additional screens from this
inventory.

NOTE (2026-04-XX, #672 phase 2): SummaryScreen, MigrationOverviewScreen,
MigrationReviewScreen removed — replaced by installer/flow/ helpers
(main.py failure loop + migration_flow.prompt_migration_action +
prompt_migration_review).
```

Also remove these screens from the SCREEN INVENTORY + PER-SCREEN WIDGET ID MAP blocks if they're still listed there.

- [ ] **Step 2: Verify**

```bash
uv run python -c "import installer.tests.e2e.test_snapshots"
```

- [ ] **Step 3: Commit**

```bash
git add installer/tests/e2e/test_snapshots.py
git commit -m "docs(installer/672): update snapshot inventory — 3 screens removed (P2)"
```

---

## Task 7: Snapshot regression tests for migration_flow output

**Files:**
- Create: `installer/tests/flow/test_migration_flow_snapshot.py`

- [ ] **Step 1: Write snapshot tests**

```python
# installer/tests/flow/test_migration_flow_snapshot.py
from pathlib import Path

import pytest
from rich.console import Console

from installer.flow.migration_flow import (
    prompt_migration_action,
    prompt_migration_review,
    show_dry_run_preview,
)
from installer.migrations.types import MigrationPlan, PendingProject, TodoRef


def _p(name: str) -> PendingProject:
    return PendingProject(
        name=name,
        path=Path("/tmp") / name,
        schema_version_path=Path("/tmp") / name / ".schema-version",
        current_version=1,
    )


def _plan() -> MigrationPlan:
    parent = TodoRef(id="1", title="parent")
    c1 = TodoRef(id="1.1", title="child1", parent="1")
    c2 = TodoRef(id="1.2", title="child2", parent="1")
    return MigrationPlan(
        project=_p("alpha"),
        parents=[parent],
        children=[c1, c2],
        integration_actions={"todoist": [], "trello": []},
    )


def test_overview_snapshot(monkeypatch: pytest.MonkeyPatch, snapshot) -> None:
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "q")
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    prompt_migration_action(
        pending=[_p("alpha"), _p("beta")],
        integration_map={"alpha": {"todoist"}, "beta": set()},
        counts={"alpha": (2, 3), "beta": (0, 0)},
        console=console,
    )
    assert console.export_text() == snapshot


def test_review_snapshot(monkeypatch: pytest.MonkeyPatch, snapshot) -> None:
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "s")
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    prompt_migration_review(
        plan=_plan(), backup_preview="/tmp/backup/alpha", console=console
    )
    assert console.export_text() == snapshot


def test_dry_run_snapshot(snapshot) -> None:
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    show_dry_run_preview(_plan(), console)
    assert console.export_text() == snapshot
```

- [ ] **Step 2: Generate goldens**

```bash
cd installer && uv run pytest tests/flow/test_migration_flow_snapshot.py --snapshot-update -v
```

- [ ] **Step 3: Re-run without flag**

```bash
cd installer && uv run pytest tests/flow/test_migration_flow_snapshot.py -v
```

Expected: 3 PASS.

- [ ] **Step 4: Commit**

```bash
git add installer/tests/flow/test_migration_flow_snapshot.py installer/tests/flow/__snapshots__/
git commit -m "test(installer/672): add syrupy snapshots for migration_flow output (P2)"
```

---

## Task 8: Full test + FF-merge to dev + watch CI

- [ ] **Step 1: Full repo test suite**

```bash
cd <repo root> && just test 2>&1 | tail -15
```

Expected: all pass (modulo known unrelated flakes).

- [ ] **Step 2: Grep hygiene — no remaining references to deleted screens**

```bash
grep -rn "SummaryScreen\|PluginOutcome\|MigrationOverviewScreen\|MigrationReviewScreen\|DryRunPreviewScreen" installer/ --include='*.py'
```

Expected: zero hits.

- [ ] **Step 3: FF-merge + push**

```bash
git checkout dev
git merge --ff-only feat/672-p2-readonly-screens
git push origin dev
```

- [ ] **Step 4: Watch CI**

```bash
gh run watch $(gh run list --branch dev --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status
```

If CI fails, investigate. Known failure pattern from P1: subprocess calls to `claude` binary fail in CI when tests don't mock — apply the same mock pattern if new tests hit this.

- [ ] **Step 5: Update todo 672 notes via `mcp__plugin_proj_proj__todo_notes_append`:**

Record commits shipped + what's ported + any new follow-up todos auto-captured during review.

---

## Self-review notes for the implementer

- **Task 4 is the largest risk.** The `run_migration_tui` restructure touches the full migration state machine. If any existing migration e2e test uses `pilot.press(...)` against the old `MigrationApp`, those tests need rewriting — likely a separate follow-up todo rather than inline fix.
- **`_make_outcome_from_runner` helper:** may not exist. The original `_after_review` inlined the `MigrationOutcome(...)` construction. Either extract it or inline the same construction logic.
- **Pre-existing snapshot flakes** on wizard/plugin_select/integration_config/advanced_config screens are NOT your concern. Ignore them.
- **If the `MigrationPlan` type doesn't exist** (spec references `installer.migrations.types.MigrationPlan`) — verify the module's actual types before writing tests. Adjust imports.

## After P2 lands

Subsequent phases are: P3 (confirm + corrupt_yaml + detection), P4 (config_diff + hooks_diff), P5 (update + plugin_select — first prompt_toolkit work), P6 (advanced_config + integration_config screens), P7 (wizard), P8 (final Textual removal). Each gets its own plan.
