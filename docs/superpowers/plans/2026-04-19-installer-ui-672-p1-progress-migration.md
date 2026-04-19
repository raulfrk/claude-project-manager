# Installer UI Migration — Phase 1: Progress Screens → Rich

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port `installer/screens/progress.py` (ProgressScreen) + `installer/screens/migration_progress.py` (MigrationProgressScreen, actually a summary-table screen) from Textual to Rich, establishing the cross-phase scaffolding (`installer/flow/` package, shared Rich `Console`, text-based snapshot infrastructure) that subsequent phases (P2-P7) will reuse.

**Architecture:** MigrationProgressScreen is read-only — swap directly to `show_migration_summary(outcomes, console)` calling a Rich `Table`. ProgressScreen displays progress during install work; Textual owns the terminal while its App runs, so porting it requires extracting install-execution from Textual's worker model into plain-Python code that runs before or after the Textual App. In this phase we keep Textual at the top level but have the install worker call `run_install_with_progress(plan, console)` which uses `rich.progress.Progress` — executed only after the Textual `ConfirmScreen` dismisses the Textual app. Subsequent phases shrink Textual's footprint further until P8 deletes it entirely.

**Tech Stack:** Python 3.13, Rich 13+, pytest, pytest-snapshot (new test dep), existing `subprocess` / `asyncio` patterns.

**Spec:** `docs/superpowers/specs/2026-04-19-installer-ui-framework-migration-design.md`

---

## File Structure

**Created:**
- `installer/flow/__init__.py` — package
- `installer/flow/console.py` — shared `Console` factory (`get_console()` returns a singleton)
- `installer/flow/install_progress.py` — `run_install_with_progress(plan, console)` using `rich.progress.Progress`
- `installer/flow/migration_summary.py` — `show_migration_summary(outcomes, console)` using Rich `Table`
- `installer/tests/flow/__init__.py`
- `installer/tests/flow/test_console.py` — console factory tests
- `installer/tests/flow/test_install_progress.py` — install-progress unit tests (pipe-input driven)
- `installer/tests/flow/test_migration_summary.py` — migration-summary snapshot tests

**Modified:**
- `installer/app.py` — `InstallerApp._run_install_worker`, `_run_update_worker`, `_run_reinstall_worker`, `_run_uninstall_worker`, `_run_status_install_worker`: replace inline `progress.write_log / progress.advance` loops with a `Plan` dataclass returned to `main.py`; `main.py` runs the plan through `run_install_with_progress` after the Textual app exits. (Aggregated change — one function per worker path.)
- `installer/app.py::run_migration_tui` — line 975: replace `self.push_screen(MigrationProgressScreen(outcomes=outcomes))` with post-exit call to `show_migration_summary(outcomes, console)`.
- `installer/main.py` — add post-Textual-exit call sequence for install and migration paths.
- `installer/tests/test_app.py` — any asserts on `ProgressScreen` / `MigrationProgressScreen` usage updated to match new flow.
- `pyproject.toml` — add `pytest-snapshot` to test deps.

**Deleted (at the end of the phase):**
- `installer/screens/progress.py`
- `installer/screens/migration_progress.py`
- `installer/tests/test_progress_screen.py`
- `installer/tests/e2e/test_snapshots_confirm_progress.py` (progress half of it — verify it doesn't also cover confirm)
- `installer/tests/e2e/snapshots/progress_*.svg`
- `installer/tests/e2e/snapshots/migration_progress_*.svg` (if any)
- `installer/tests/migrations/test_screens.py::test_progress_summary_snapshot`

**Latent bug fixed (from spec §Latent bug inventory):**
- B12 — async-race doc for ProgressScreen wait_ready — **eliminated, not documented**: the Rich port doesn't have a wait_ready concept because `rich.progress.Progress` is synchronous context-managed.

---

## Task 1: Scaffold `installer/flow/` package + shared Console

**Files:**
- Create: `installer/flow/__init__.py`
- Create: `installer/flow/console.py`
- Create: `installer/tests/flow/__init__.py`
- Create: `installer/tests/flow/test_console.py`

- [ ] **Step 1: Write the failing test**

Create `installer/tests/flow/test_console.py`:

```python
# installer/tests/flow/test_console.py
from rich.console import Console

from installer.flow.console import get_console, reset_console


def test_get_console_returns_rich_console() -> None:
    reset_console()
    c = get_console()
    assert isinstance(c, Console)


def test_get_console_is_singleton() -> None:
    reset_console()
    assert get_console() is get_console()


def test_reset_console_clears_singleton() -> None:
    first = get_console()
    reset_console()
    second = get_console()
    assert first is not second
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd installer && uv run pytest tests/flow/test_console.py -v
```

Expected: `ModuleNotFoundError: No module named 'installer.flow.console'` (or import-time FAIL).

- [ ] **Step 3: Create the package `__init__` files**

Create `installer/flow/__init__.py`:

```python
# installer/flow/__init__.py
"""Plain-Python flow helpers that drive the installer without Textual.

Each helper takes an `InstallState` (or similar) and a `rich.Console`, prompts
or reports via Rich (and later prompt_toolkit), and returns updated state.
"""
```

Create `installer/tests/flow/__init__.py` (empty file).

- [ ] **Step 4: Implement `get_console`**

Create `installer/flow/console.py`:

```python
# installer/flow/console.py
"""Shared Rich Console singleton for the installer flow layer."""

from __future__ import annotations

from rich.console import Console

_console: Console | None = None


def get_console() -> Console:
    """Return the shared Rich Console, creating it on first call."""
    global _console
    if _console is None:
        _console = Console()
    return _console


def reset_console() -> None:
    """Drop the cached console. For tests only."""
    global _console
    _console = None
```

- [ ] **Step 5: Run test to verify it passes**

```bash
cd installer && uv run pytest tests/flow/test_console.py -v
```

Expected: 3 PASS.

- [ ] **Step 6: Commit**

```bash
git add installer/flow/__init__.py installer/flow/console.py installer/tests/flow/__init__.py installer/tests/flow/test_console.py
git commit -m "feat(installer/672): add flow/ package + Rich Console factory (P1)"
```

---

## Task 2: Port MigrationProgressScreen → `show_migration_summary`

**Files:**
- Create: `installer/flow/migration_summary.py`
- Create: `installer/tests/flow/test_migration_summary.py`
- Modify: `installer/app.py::run_migration_tui` (line 975)
- Delete: `installer/screens/migration_progress.py` (at end of task)

**Context:** `MigrationProgressScreen` is misnamed — it shows a read-only outcome summary table (✓/◐/✗ counts + per-project details) AFTER migration finishes. It has no progress bar. Rename on port: `show_migration_summary(outcomes, console)`. The `MigrationOutcome` dataclass moves with it.

- [ ] **Step 1: Write the failing test**

Create `installer/tests/flow/test_migration_summary.py`:

```python
# installer/tests/flow/test_migration_summary.py
from rich.console import Console

from installer.flow.migration_summary import MigrationOutcome, show_migration_summary


def test_summary_renders_counts_header() -> None:
    console = Console(record=True, width=80)
    outcomes = [
        MigrationOutcome(project="alpha", ok=True, resync_partial=False, backup="b1"),
        MigrationOutcome(project="beta", ok=True, resync_partial=True, backup="b2"),
        MigrationOutcome(project="gamma", ok=False, resync_partial=False, backup="b3", error="boom"),
    ]

    show_migration_summary(outcomes, console)

    text = console.export_text()
    assert "1 ok" in text
    assert "1 partial-resync" in text
    assert "1 failed" in text


def test_summary_renders_per_project_row() -> None:
    console = Console(record=True, width=80)
    outcomes = [
        MigrationOutcome(project="demo", ok=False, resync_partial=False, backup="bdir", error="migration failed: xyz"),
    ]
    show_migration_summary(outcomes, console)
    text = console.export_text()
    assert "demo" in text
    assert "bdir" in text
    assert "migration failed: xyz" in text


def test_summary_handles_empty_outcomes() -> None:
    console = Console(record=True, width=80)
    show_migration_summary([], console)
    text = console.export_text()
    assert "0 ok" in text
    assert "0 failed" in text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd installer && uv run pytest tests/flow/test_migration_summary.py -v
```

Expected: `ModuleNotFoundError: No module named 'installer.flow.migration_summary'`.

- [ ] **Step 3: Implement `show_migration_summary`**

Create `installer/flow/migration_summary.py`:

```python
# installer/flow/migration_summary.py
"""Display the read-only outcome summary after a migration run."""

from __future__ import annotations

from dataclasses import dataclass

from rich.console import Console
from rich.table import Table


@dataclass(frozen=True)
class MigrationOutcome:
    """Result for a single project in a migration run."""

    project: str
    ok: bool
    resync_partial: bool
    backup: str
    error: str | None = None


def show_migration_summary(outcomes: list[MigrationOutcome], console: Console) -> None:
    """Render the post-migration outcome table to ``console``.

    Prints a counts-header line (``✓ N ok ◐ M partial-resync ✗ K failed``)
    followed by a table with one row per project.
    """
    ok = sum(1 for o in outcomes if o.ok and not o.resync_partial)
    partial = sum(1 for o in outcomes if o.ok and o.resync_partial)
    failed = sum(1 for o in outcomes if not o.ok)

    console.print(
        f"[bold]Results[/]  [green]✓ {ok} ok[/]  "
        f"[yellow]◐ {partial} partial-resync[/]  "
        f"[red]✗ {failed} failed[/]",
    )

    table = Table(show_header=True, header_style="bold")
    table.add_column("Status", width=6)
    table.add_column("Project")
    table.add_column("Backup")
    table.add_column("Details")
    for o in outcomes:
        if not o.ok:
            status = "[red]✗[/]"
        elif o.resync_partial:
            status = "[yellow]◐[/]"
        else:
            status = "[green]✓[/]"
        table.add_row(status, o.project, o.backup, o.error or "")
    console.print(table)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd installer && uv run pytest tests/flow/test_migration_summary.py -v
```

Expected: 3 PASS.

- [ ] **Step 5: Rewire `run_migration_tui` to call the new helper**

In `installer/app.py`, find the migration summary push (around line 975) and change:

```python
# Before:
self.push_screen(MigrationProgressScreen(outcomes=outcomes))
```

to:

```python
# After: defer summary to post-exit (Textual owns terminal during push_screen).
# Caller (main.py) reads the attribute after App.run() returns.
self._migration_outcomes = outcomes
self.exit()
```

Then in the same `InstallerApp` class, add a new field initialization in `__init__`:

```python
self._migration_outcomes: list[MigrationOutcome] | None = None
```

And update the `MigrationOutcome` import at the top of `installer/app.py`:

```python
# Replace:
from installer.screens.migration_progress import MigrationOutcome, MigrationProgressScreen

# With:
from installer.flow.migration_summary import MigrationOutcome, show_migration_summary
```

- [ ] **Step 6: Call the helper from `main.py` after the Textual app exits**

Find the `run_migration_tui(...)` call site in `installer/main.py` (grep for `run_migration_tui`). After the call returns, add:

```python
from installer.flow.console import get_console
from installer.flow.migration_summary import show_migration_summary
# ... existing call ...
if app._migration_outcomes is not None:
    show_migration_summary(app._migration_outcomes, get_console())
```

(If `run_migration_tui` currently returns the exit code only, refactor its return to include the outcomes OR expose the outcomes via an app attribute as shown above. Grep the function to see.)

- [ ] **Step 7: Delete the old Textual screen + unused imports**

```bash
rm installer/screens/migration_progress.py
rm -f installer/tests/e2e/snapshots/migration_progress_*.svg
```

Grep for leftover imports:

```bash
grep -rn "migration_progress" installer/
```

Update any remaining imports to point at `installer.flow.migration_summary`.

- [ ] **Step 8: Update `installer/screens/__init__.py`**

Remove any `from .migration_progress import ...` exports. If none, no change needed.

- [ ] **Step 9: Delete/update matching snapshot tests**

```bash
grep -n "MigrationProgressScreen\|migration_progress" installer/tests/
```

For any test in `installer/tests/migrations/test_screens.py` that uses `MigrationProgressScreen`: delete the test function. If the whole file becomes empty of relevant tests, delete the file.

- [ ] **Step 10: Run full install tests**

```bash
cd installer && uv run pytest tests/flow/test_migration_summary.py tests/migrations/ -v
```

Expected: all pass (both new tests and existing migration-layer tests).

- [ ] **Step 11: Commit**

```bash
git add installer/flow/migration_summary.py installer/tests/flow/test_migration_summary.py installer/app.py installer/main.py installer/screens/__init__.py installer/tests/migrations/test_screens.py
git rm installer/screens/migration_progress.py
git rm -rf installer/tests/e2e/snapshots/migration_progress_*.svg 2>/dev/null || true
git commit -m "feat(installer/672): port MigrationProgressScreen → flow.show_migration_summary (P1)

Renames the misnamed 'progress' screen to 'summary' (it's a read-only
outcome table, no progress bar). Rich Table replaces Textual DataTable.
Call site moved out of the Textual push_screen path to run after the
Textual app exits, freeing the terminal for Rich.

Part of #672 Phase 1."
```

---

## Task 3: Add `pytest-snapshot` dep + scaffold first text snapshot

**Files:**
- Modify: `pyproject.toml` (add test dep)
- Create: `installer/tests/flow/test_migration_summary_snapshot.py`
- Create: `installer/tests/flow/__snapshots__/` (pytest-snapshot creates on first run)

- [ ] **Step 1: Add `pytest-snapshot` to test deps**

In `pyproject.toml`, add `pytest-snapshot>=0.9` to the `[dependency-groups].test` (or equivalent) block. Run:

```bash
cd <repo root> && uv sync --group test
```

- [ ] **Step 2: Write the failing snapshot test**

Create `installer/tests/flow/test_migration_summary_snapshot.py`:

```python
# installer/tests/flow/test_migration_summary_snapshot.py
from rich.console import Console

from installer.flow.migration_summary import MigrationOutcome, show_migration_summary


def test_migration_summary_all_ok_snapshot(snapshot) -> None:
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    outcomes = [
        MigrationOutcome(project="alpha", ok=True, resync_partial=False, backup="b1"),
        MigrationOutcome(project="beta", ok=True, resync_partial=False, backup="b2"),
    ]
    show_migration_summary(outcomes, console)
    snapshot.assert_match(console.export_text(), "migration_summary_all_ok.txt")


def test_migration_summary_mixed_snapshot(snapshot) -> None:
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    outcomes = [
        MigrationOutcome(project="alpha", ok=True, resync_partial=False, backup="b1"),
        MigrationOutcome(project="beta", ok=True, resync_partial=True, backup="b2"),
        MigrationOutcome(project="gamma", ok=False, resync_partial=False, backup="b3", error="boom"),
    ]
    show_migration_summary(outcomes, console)
    snapshot.assert_match(console.export_text(), "migration_summary_mixed.txt")
```

- [ ] **Step 3: Run to create golden files**

```bash
cd installer && uv run pytest tests/flow/test_migration_summary_snapshot.py --snapshot-update -v
```

Expected: tests pass, golden files created at `installer/tests/flow/__snapshots__/test_migration_summary_snapshot/*.txt`.

- [ ] **Step 4: Run again to confirm stability**

```bash
cd installer && uv run pytest tests/flow/test_migration_summary_snapshot.py -v
```

Expected: 2 PASS (no diff).

- [ ] **Step 5: Inspect the generated goldens**

```bash
cat installer/tests/flow/__snapshots__/test_migration_summary_snapshot/migration_summary_all_ok.txt
```

Confirm it looks like a rendered summary (e.g., `Results  ✓ 2 ok  ◐ 0 partial-resync  ✗ 0 failed\n[table]`).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock installer/tests/flow/test_migration_summary_snapshot.py installer/tests/flow/__snapshots__/
git commit -m "test(installer/672): add pytest-snapshot + text golden for migration_summary (P1)"
```

---

## Task 4: Extract install-plan calculation from Textual worker

**Files:**
- Modify: `installer/app.py` — split `_run_status_install_worker` (lines 428-550 or similar) and peer workers into (a) plan calculation (b) execution.
- Create: `installer/flow/install_plan.py` — `InstallPlan` dataclass + `execute_install_plan(plan, console)` that runs the mutations.

**Context:** Currently each Textual worker interleaves "compute what to do" (marketplace check, name resolution, selection logic) with "apply side effects" (install/uninstall calls). Splitting these is a prerequisite for running the side-effect phase outside Textual with a Rich progress bar.

- [ ] **Step 1: Write the failing test**

Create `installer/tests/flow/test_install_plan.py`:

```python
# installer/tests/flow/test_install_plan.py
from rich.console import Console

from installer.flow.install_plan import InstallAction, InstallPlan, execute_install_plan


def test_execute_calls_hooks_in_order(monkeypatch) -> None:
    calls: list[tuple[str, str]] = []

    def fake_install(pid: str) -> None:
        calls.append(("install", pid))

    def fake_uninstall(pid: str) -> None:
        calls.append(("uninstall", pid))

    monkeypatch.setattr("installer.flow.install_plan.install_plugin", fake_install)
    monkeypatch.setattr("installer.flow.install_plan.uninstall_plugin", fake_uninstall)

    plan = InstallPlan(
        description="Test plan",
        actions=[
            InstallAction(plugin_id="a@m", action="install"),
            InstallAction(plugin_id="b@m", action="uninstall"),
        ],
    )
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    result = execute_install_plan(plan, console)

    assert calls == [("install", "a@m"), ("uninstall", "b@m")]
    assert result.success_count == 2
    assert result.failure_count == 0


def test_execute_reports_failure(monkeypatch) -> None:
    from installer.errors import InstallerError

    def fake_install(pid: str) -> None:
        raise InstallerError(f"boom {pid}")

    monkeypatch.setattr("installer.flow.install_plan.install_plugin", fake_install)

    plan = InstallPlan(
        description="Test plan",
        actions=[InstallAction(plugin_id="a@m", action="install")],
    )
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    result = execute_install_plan(plan, console)

    assert result.success_count == 0
    assert result.failure_count == 1
    assert result.failures[0].plugin_id == "a@m"
    assert "boom" in result.failures[0].error
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd installer && uv run pytest tests/flow/test_install_plan.py -v
```

Expected: `ModuleNotFoundError`.

- [ ] **Step 3: Implement `install_plan.py`**

Create `installer/flow/install_plan.py`:

```python
# installer/flow/install_plan.py
"""Install-action plan + executor.

Split off from the Textual worker model so the side-effect phase can run
outside a Textual App (Textual owns the terminal; Rich progress needs it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from installer.errors import InstallerError
from installer.plugin_cli import install_plugin, uninstall_plugin


Action = Literal["install", "uninstall", "reinstall"]


@dataclass(frozen=True)
class InstallAction:
    plugin_id: str  # fully qualified, e.g. "proj@claude-project-manager"
    action: Action


@dataclass(frozen=True)
class InstallFailure:
    plugin_id: str
    action: Action
    error: str


@dataclass
class InstallResult:
    success_count: int = 0
    failure_count: int = 0
    failures: list[InstallFailure] = field(default_factory=list)


@dataclass(frozen=True)
class InstallPlan:
    description: str
    actions: list[InstallAction]


def execute_install_plan(plan: InstallPlan, console: Console) -> InstallResult:
    """Run each action in the plan, updating a Rich progress bar.

    Catches ``InstallerError`` per action so one failure doesn't abort the batch.
    """
    result = InstallResult()
    total = len(plan.actions)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(plan.description, total=total)
        for action in plan.actions:
            progress.update(task, description=f"{action.action.capitalize()}ing {action.plugin_id}...")
            try:
                if action.action == "install":
                    install_plugin(action.plugin_id)
                elif action.action == "uninstall":
                    uninstall_plugin(action.plugin_id)
                elif action.action == "reinstall":
                    uninstall_plugin(action.plugin_id)
                    install_plugin(action.plugin_id)
                result.success_count += 1
            except InstallerError as exc:
                result.failures.append(
                    InstallFailure(
                        plugin_id=action.plugin_id,
                        action=action.action,
                        error=str(exc),
                    ),
                )
                result.failure_count += 1
            progress.advance(task)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd installer && uv run pytest tests/flow/test_install_plan.py -v
```

Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add installer/flow/install_plan.py installer/tests/flow/test_install_plan.py
git commit -m "feat(installer/672): add InstallPlan + execute_install_plan with Rich progress (P1)"
```

---

## Task 5: Wire the new plan/executor into the install-path workers

**Files:**
- Modify: `installer/app.py` — `_run_status_install_worker` (~line 428) + `_run_install_worker` (~line 625) + `_run_reinstall_worker` (~line 725) + `_run_uninstall_worker` (~line 816).
- Modify: `installer/main.py` — after `InstallerApp.run()` exits with a plan, call `execute_install_plan(plan, get_console())`.

**Context:** Each current worker does `progress = ProgressScreen(...); self.push_screen(progress); ... await progress.wait_ready(); ... progress.advance(...)`. The new model: each worker COLLECTS an `InstallPlan` (no side effects, no progress), stores it on the app, then exits. `main.py` reads `app.install_plan` post-exit and invokes `execute_install_plan`.

- [ ] **Step 1: Write the failing integration test**

Create `installer/tests/flow/test_install_path_integration.py`:

```python
# installer/tests/flow/test_install_path_integration.py
from unittest.mock import MagicMock, patch

from installer.app import InstallerApp
from installer.flow.install_plan import InstallPlan, InstallAction


def test_status_install_worker_produces_plan(monkeypatch) -> None:
    """After collecting user actions, the app should expose an InstallPlan
    instead of immediately running them via a Textual ProgressScreen."""
    monkeypatch.setattr("installer.app.get_available_plugins", lambda: ["proj@m", "router@m"])
    monkeypatch.setattr("installer.app.get_installed_plugins", lambda: [])
    monkeypatch.setattr("installer.app.check_marketplace_registered", lambda: True)

    app = InstallerApp()
    app._pending_actions = [("proj", "install"), ("router", "install")]

    plan = app._build_install_plan(app._pending_actions)

    assert isinstance(plan, InstallPlan)
    assert len(plan.actions) == 2
    assert plan.actions[0].plugin_id == "proj@m"
    assert plan.actions[0].action == "install"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd installer && uv run pytest tests/flow/test_install_path_integration.py -v
```

Expected: FAIL — `_build_install_plan` does not exist.

- [ ] **Step 3: Add `_build_install_plan` helper to `InstallerApp`**

In `installer/app.py`, add method (place it near `_start_status_install`, around line 411):

```python
def _build_install_plan(
    self, actions: list[tuple[str, str]]
) -> InstallPlan:
    """Resolve plugin names → IDs and build an InstallPlan (no side effects).

    Mirrors the name_to_id resolution used elsewhere; kept here so callers
    don't need a live Textual context.
    """
    try:
        available = get_available_plugins()
        installed_ids = get_installed_plugins()
    except InstallerError:
        available, installed_ids = [], []

    name_to_id: dict[str, str] = {}
    for pid in available + installed_ids:
        name_to_id.setdefault(pid.split("@")[0], pid)

    install_actions = [
        InstallAction(
            plugin_id=name_to_id.get(name, f"{name}@claude-project-manager"),
            action=action,  # type: ignore[arg-type]
        )
        for name, action in actions
    ]
    return InstallPlan(
        description=f"Processing {len(actions)} plugin actions...",
        actions=install_actions,
    )
```

Add import at the top of `installer/app.py`:

```python
from installer.flow.install_plan import InstallAction, InstallPlan
```

- [ ] **Step 4: Run the new test**

```bash
cd installer && uv run pytest tests/flow/test_install_path_integration.py -v
```

Expected: 1 PASS.

- [ ] **Step 5: Replace `_start_status_install` body**

In `installer/app.py`, replace the body of `_start_status_install` (current lines ~411-426) with:

```python
def _start_status_install(self) -> None:
    """Build the install plan and exit; main.py runs it via Rich."""
    actions = getattr(self, "_pending_actions", [])
    if not actions:
        self.exit()
        return
    self._install_plan = self._build_install_plan(actions)
    self.exit()
```

Add to `InstallerApp.__init__` (line 150-ish — search for the `self._hooks_diffs` initialization):

```python
self._install_plan: InstallPlan | None = None
```

Repeat the pattern for `_run_install_worker` (~line 625), `_run_reinstall_worker` (~line 725), `_run_uninstall_worker` (~line 816). Each worker today looks roughly like:

```python
# BEFORE — _run_install_worker (simplified):
async def _run_install_worker(self, selected: list[str], progress: ProgressScreen) -> None:
    await progress.wait_ready()
    for name in selected:
        progress.write_log(f"Installing {name}...")
        await asyncio.to_thread(install_plugin, resolve_id(name))
        progress.advance(1)
```

Replace with the plan-builder-then-exit pattern:

```python
# AFTER — _run_install_worker (no async, no ProgressScreen):
def _run_install_worker(self, selected: list[str]) -> None:
    available = get_available_plugins()
    installed_ids = get_installed_plugins()
    name_to_id = {pid.split("@")[0]: pid for pid in available + installed_ids}

    actions = [
        InstallAction(
            plugin_id=name_to_id.get(n, f"{n}@claude-project-manager"),
            action="install",
        )
        for n in selected
    ]
    self._install_plan = InstallPlan(
        description=f"Installing {len(selected)} plugins...",
        actions=actions,
    )
    self.exit()
```

Key differences per worker:

| Worker | Action kind | Extra resolution |
|---|---|---|
| `_run_install_worker` | `"install"` | None |
| `_run_update_worker` | `"install"` (update = install via marketplace) | pre-reads versions; no change to plan shape |
| `_run_reinstall_worker` | `"reinstall"` | None |
| `_run_uninstall_worker` | `"uninstall"` | None |

Delete the `await progress.wait_ready()` and every `progress.write_log / progress.advance` call in each worker — those responsibilities move to `execute_install_plan`. Delete the `async` qualifier + `asyncio.to_thread` calls (no longer needed — execution runs outside Textual). Delete the `ProgressScreen` parameter from each signature. Delete the `push_screen(progress, ...)` + `run_worker(...)` call sites in the methods that previously spawned these workers.

For each worker that had a push_screen call site (grep `ProgressScreen(` in app.py — 6 hits), replace the block with a single call to the now-sync worker + nothing else:

```python
# BEFORE (at e.g. line 622 of app.py):
progress = ProgressScreen(description="Installing plugins...", total=len(selected))
self.push_screen(progress, callback=self._on_progress_done)
self.run_worker(
    self._run_install_worker(selected, progress),
    exclusive=True,
)

# AFTER:
self._run_install_worker(selected)
```

- [ ] **Step 6: Update `main.py` to run the plan after app exit**

In `installer/main.py`, find the block that calls `app.run()` (grep for `InstallerApp()` or `app.run()`). After the call:

```python
from installer.flow.console import get_console
from installer.flow.install_plan import execute_install_plan

# ... existing app.run() ...
if app._install_plan is not None:
    result = execute_install_plan(app._install_plan, get_console())
    if result.failure_count:
        for failure in result.failures:
            console = get_console()
            console.print(
                f"[red]✗[/] {failure.plugin_id} ({failure.action}): {failure.error}",
            )
        return 1
    return 0
return app.return_code or 0
```

- [ ] **Step 7: Run the full install-path test suite**

```bash
cd installer && uv run pytest tests/test_app.py tests/flow/ tests/e2e/test_install_flow.py -v
```

Expected: existing behavioral tests still pass; update any asserts that referenced `ProgressScreen` or `progress.advance` (they should use the new `InstallPlan.actions` shape).

If a test fails because it asserts the Textual progress pushed, rewrite that assertion to check `app._install_plan.actions`. Delete any asserts coupled to Textual progress rendering.

- [ ] **Step 8: Commit**

```bash
git add installer/app.py installer/main.py installer/tests/flow/test_install_path_integration.py installer/tests/test_app.py
git commit -m "feat(installer/672): workers build InstallPlan; main.py executes with Rich (P1)

Replaces in-worker Textual ProgressScreen.advance() loop with a plain
InstallPlan dataclass. main.py calls execute_install_plan after the
Textual app exits; Rich owns the terminal then.

Part of #672 Phase 1."
```

---

## Task 6: Delete `ProgressScreen` + related tests + snapshots

**Files:**
- Delete: `installer/screens/progress.py`
- Delete: `installer/tests/test_progress_screen.py`
- Delete: `installer/tests/e2e/test_snapshots_confirm_progress.py` (confirm progress half only — if it covers confirm too, keep confirm asserts; extract/delete progress asserts).
- Delete: `installer/tests/e2e/snapshots/progress_*.svg` + any other progress SVG goldens.

- [ ] **Step 1: Confirm no remaining references**

```bash
grep -rn "ProgressScreen\b\|from installer.screens.progress\|installer/screens/progress.py" installer/
```

Expected: zero hits outside the files being deleted. If hits remain (e.g., imports in `installer/screens/__init__.py`), fix them.

- [ ] **Step 2: Delete the screen module**

```bash
rm installer/screens/progress.py
```

- [ ] **Step 3: Delete the unit test**

```bash
rm installer/tests/test_progress_screen.py
```

- [ ] **Step 4: Inspect the confirm-progress snapshot file**

```bash
head -50 installer/tests/e2e/test_snapshots_confirm_progress.py
```

If it has tests for both `ConfirmScreen` and `ProgressScreen`:
- Keep `ConfirmScreen` tests (P3 work, not P1).
- Delete `ProgressScreen` tests from this file.

If the file is only progress tests, delete the whole file:

```bash
rm installer/tests/e2e/test_snapshots_confirm_progress.py
```

- [ ] **Step 5: Delete progress SVG goldens**

```bash
rm -f installer/tests/e2e/snapshots/progress_*.svg
```

- [ ] **Step 6: Remove `from installer.screens.progress import ...` from `screens/__init__.py`**

```bash
grep -n "progress" installer/screens/__init__.py
```

Remove any matching lines.

- [ ] **Step 7: Run the full installer test suite for regression check**

```bash
cd installer && uv run pytest tests/ -x --tb=short -q
```

Expected: all pass (modulo known `test-installer-e2e` snapshot flakes on unrelated screens — these are tracked by todo 670 and addressed by this overall migration, NOT this phase).

- [ ] **Step 8: Commit**

```bash
git add -A installer/
git commit -m "chore(installer/672): delete ProgressScreen + snapshot tests + SVG goldens (P1)"
```

---

## Task 7: Update screen inventory docstring in `test_snapshots.py`

**Files:**
- Modify: `installer/tests/e2e/test_snapshots.py` — remove `ProgressScreen` from the "SCREEN INVENTORY" docstring + PER-SCREEN WIDGET ID MAP.

- [ ] **Step 1: Edit the docstring**

Open `installer/tests/e2e/test_snapshots.py`. Remove the `ProgressScreen` bullet from the screen-inventory list and the `ProgressScreen: AUTO_FOCUS = ""` block from the widget-id map. Add a note at the top:

```python
"""SVG golden-file snapshot tests for remaining TUI screens.

NOTE (2026-04-19, #672 phase 1): ProgressScreen removed — replaced by
installer/flow/install_plan.py::execute_install_plan which uses Rich.
Subsequent phases will remove additional screens from this inventory.
"""
```

- [ ] **Step 2: Commit**

```bash
git add installer/tests/e2e/test_snapshots.py
git commit -m "docs(installer/672): update snapshot inventory — ProgressScreen removed (P1)"
```

---

## Task 8: Full test + FF-merge to dev

- [ ] **Step 1: Run full project test suite**

```bash
cd <repo root> && just test
```

Expected: all pass (modulo known CI snapshot flakes on screens NOT yet ported — those are P2-P7 work).

- [ ] **Step 2: Confirm grep hygiene**

```bash
grep -rn "ProgressScreen\|MigrationProgressScreen\|from installer.screens.progress\|from installer.screens.migration_progress" installer/
```

Expected: zero hits.

```bash
grep -rn "ProgressScreen\|MigrationProgressScreen" installer/screens/ installer/flow/
```

Expected: zero hits.

- [ ] **Step 3: Run installer test suite in isolation**

```bash
cd installer && uv run pytest tests/ --no-cov -q
```

Expected: all pass except the known remaining snapshot flakes on wizard/plugin_select/etc. — those are tracked by 670 and resolved by P2-P7.

- [ ] **Step 4: FF-merge the feature branch to dev**

```bash
cd <repo root>
git fetch origin dev
git checkout dev
git merge --ff-only feat/672-p1-progress-migration
git push origin dev
```

- [ ] **Step 5: Watch CI**

```bash
gh run watch $(gh run list --branch dev --limit 1 --json databaseId --jq '.[0].databaseId') --exit-status
```

Expected: all jobs pass except `test-installer-e2e` which may still fail on wizard/plugin_select snapshots. Those are P2-P7 work.

- [ ] **Step 6: Mark todo 672 phase 1 complete**

Use `mcp__plugin_proj_proj__todo_notes_append` on todo 672 to record:

```
Phase 1 shipped on dev: <commit hashes>. ProgressScreen + MigrationProgressScreen ported to installer/flow/ (Rich-based). Text snapshots replace SVG goldens for both. ~230 LOC Textual removed, ~400 LOC Rich flow added. Next: P2 (summary + migration_overview + migration_review).
```

---

## Self-review notes (for implementer before starting)

- **Task 5 is the biggest risk.** The non-status install paths (`_run_install_worker`, `_run_update_worker`, `_run_reinstall_worker`, `_run_uninstall_worker`) each have their own action-collection logic. Budget extra time for inlining `name_to_id` resolution inside `_build_install_plan` variants OR passing a shared resolver.
- **If `test_snapshots_confirm_progress.py` covers both confirm+progress**, the file rename + split can become its own task — don't inline it into Task 6 unless it's truly trivial.
- **`main.py` structure varies by mode** (install, update, migrate, reinstall, uninstall). Verify each mode's exit path calls `execute_install_plan` when a plan was built, and skips the call otherwise.
- **Do not delete `installer/screens/__init__.py`** — other screens still live there. Just remove the relevant imports.
- **Do not remove Textual from deps** — this is P8 work. Textual stays until all screens are ported.

## After Phase 1 lands

Subsequent phases (P2-P7) each get their own plan under `docs/superpowers/plans/2026-04-XX-installer-ui-672-pN-<screens>.md`. Each follows the same structure:
1. Port one or two related screens to `installer/flow/`.
2. Wire main.py / app.py to call the new flow helpers.
3. Delete the ported Textual screen + its SVG goldens.
4. Add text-based snapshot tests for the new flow.
5. FF-merge, watch CI, update todo 672 notes.

P8 is different — it removes Textual from deps, deletes residual `installer/app.py` scaffolding, and verifies exit criteria from the spec. That plan depends on P1-P7 being green on dev for 24+ hours.
