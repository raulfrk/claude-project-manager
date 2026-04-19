"""Textual TUI application for the installer."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import sys
from pathlib import Path
from typing import Any

from claudemd import ensure_managed_section
from textual.app import App, ComposeResult
from textual.widgets import Footer, Static

from installer._config_loader import ConfigLoadError, load_existing_yaml
from installer.cleanup import (
    _cache_dir_for_reinstall,
    _marketplace_path_for_reinstall,
    prune_orphaned_plugins,
    prune_stale_versions,
    scan_stale_cache,
)
from installer.detect import InstallState, detect_existing
from installer.errors import InstallerError
from installer.plugin_cli import (
    get_available_plugins,
    get_installed_plugins,
)
from installer.plugin_status import (
    PLUGIN_NAME_RE,
    PluginStatus,
    build_plugin_status_list,
)
from installer.flow.install_plan import InstallAction, InstallPlan
from installer.screens.confirm import ConfirmOption, ConfirmResult, ConfirmScreen
from installer.screens.detection import DetectionScreen, PluginDetectionRow
from installer.screens.integration_config import (
    BaseIntegrationScreen,
    JiraConfigScreen,
    TodoistConfigScreen,
    TrelloConfigScreen,
)
from installer.screens.plugin_select import PluginStatusScreen
from installer.screens.update import UpdateScreen
from installer.screens.wizard import WizardScreen
from installer.update import (
    _read_installed_version,
    _read_marketplace_versions,
    compare_versions,
)

logger = logging.getLogger("installer.app")


class InstallerApp(App):
    """Claude Project Manager installer TUI."""

    CSS = """
    Screen {
        align: center middle;
    }

    /* -- Global theme -- */

    Footer {
        background: $primary-background;
        color: $text;
    }

    Button {
        min-width: 16;
    }

    Button:focus {
        text-style: bold;
    }

    DataTable {
        scrollbar-size: 1 1;
    }

    DataTable > .datatable--cursor {
        background: $accent 30%;
        color: $text;
        text-style: bold;
    }

    Static {
        scrollbar-size: 1 1;
    }

    Input:focus {
        border: tall $accent;
    }

    Switch:focus {
        border: tall $accent;
    }

    Checkbox:focus {
        text-style: bold underline;
    }
    """

    TITLE = "Claude Project Manager — Installer"

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("escape", "back", "Back"),
    ]

    # Plugins that need proj.yaml
    _PROJ_PLUGINS = {"proj", "router", "todoist", "trello", "jira"}

    def __init__(self, mode: str = "install", args: object = None) -> None:
        super().__init__()
        self.mode = mode  # install, update, reinstall, uninstall
        self.installer_args = args
        self.selected_plugins: list[str] = []
        self.wizard_config: dict[str, Any] | None = None
        self._state: InstallState | None = None
        self._branch: str | None = getattr(args, "branch", None) if args else None
        self.install_plan: InstallPlan | None = None
        self.reinstall_message: str | None = None  # for error-path-only messages
        self.full_cleanup: bool = False  # set by uninstall path; read by main.py

    def compose(self) -> ComposeResult:
        yield Static(f"Mode: {self.mode}", id="placeholder")
        yield Footer()

    def on_mount(self) -> None:
        """Route to the appropriate screen based on mode."""
        if self.mode == "install":
            self.run_worker(self._build_status_screen(), exclusive=True)
        elif self.mode in ("update", "reinstall", "uninstall"):
            self._state = detect_existing()
            detection_rows = self._build_detection_rows(self._state)
            self.push_screen(
                DetectionScreen(
                    state=self._state,
                    plugin_rows=detection_rows,
                    title_text=f"Existing Installation — {self.mode.title()} Mode",
                ),
                callback=self._on_detection_done,
            )

    # -- Detection helpers --

    def _build_detection_rows(self, state: InstallState) -> list[PluginDetectionRow]:
        """Build detection rows comparing installed vs available versions."""
        repo_versions = _read_marketplace_versions()
        rows: list[PluginDetectionRow] = []

        all_plugins = sorted(set(state.installed_plugins) | set(repo_versions.keys()))

        for plugin_name in all_plugins:
            installed_ver = None
            if state.cache_dir is not None and plugin_name in state.installed_plugins:
                installed_ver = _read_installed_version(state.cache_dir, plugin_name)
            available_ver = repo_versions.get(plugin_name)
            rows.append(
                PluginDetectionRow(
                    plugin=plugin_name,
                    installed_version=installed_ver,
                    available_version=available_ver,
                )
            )

        return rows

    def _on_detection_done(self, proceed: bool) -> None:
        """After detection screen, route to the appropriate next screen."""
        if not proceed or self._state is None:
            self.exit()
            return

        if self.mode == "update":
            diffs = compare_versions(self._state)
            if not diffs:
                placeholder = self.query_one("#placeholder", Static)
                placeholder.update("All plugins are up to date.")
                return
            self.push_screen(
                UpdateScreen(version_diffs=diffs),
                callback=self._on_update_selected,
            )
        elif self.mode == "reinstall":
            self.push_screen(
                ConfirmScreen(
                    title="Reinstall Plugins",
                    message=(
                        "This will reinstall all installed plugins.\n"
                        "A backup will be created before any changes."
                    ),
                    options=[
                        ConfirmOption(
                            key="reset_configs",
                            label="Reset configs (remove proj.yaml, worktree.yaml)",
                            default=False,
                        ),
                    ],
                    confirm_label="Reinstall",
                    confirm_variant="warning",
                ),
                callback=self._on_reinstall_confirmed,
            )
        elif self.mode == "uninstall":
            self.push_screen(
                ConfirmScreen(
                    title="Uninstall Plugins",
                    message=(
                        "This will remove all installed plugins.\n"
                        "A backup will be created before removal."
                    ),
                    options=[
                        ConfirmOption(
                            key="full_cleanup",
                            label="Full cleanup (also remove config files)",
                            default=False,
                        ),
                    ],
                    confirm_label="Uninstall",
                    confirm_variant="error",
                ),
                callback=self._on_uninstall_confirmed,
            )

    # -- Install flow callbacks --

    async def _build_status_screen(self) -> None:
        """Fetch plugin statuses (with timeout) and push ``PluginStatusScreen``.

        Wraps ``build_plugin_status_list`` in ``asyncio.to_thread`` with a
        30-second timeout so a hanging ``claude plugin list`` call can't
        block the UI. On failure, surfaces a ``CorruptYamlScreen``-style
        error modal pattern via ``_show_error``.
        """
        try:
            statuses: list[PluginStatus] = await asyncio.wait_for(
                asyncio.to_thread(build_plugin_status_list),
                timeout=30,
            )
        except asyncio.TimeoutError:
            self._show_error(
                "Timed out while listing plugins (>30s). "
                "Is `claude plugin list` hanging?"
            )
            return
        except InstallerError as exc:
            self._show_error(f"Failed to build plugin status list: {exc}")
            return
        except ValueError as exc:
            # Invalid plugin name in marketplace — refuse to continue.
            self._show_error(str(exc))
            return

        self._plugin_statuses = statuses
        self.push_screen(
            PluginStatusScreen(statuses=statuses),
            callback=self._on_status_actions,
        )

    def _on_status_actions(self, actions: list[tuple[str, str]] | None) -> None:
        """Handle the result from ``PluginStatusScreen``.

        ``actions`` is a list of ``(plugin_name, action)`` for rows whose
        action is not ``"skip"``. Empty / None exits the app. Names are
        validated against ``PLUGIN_NAME_RE`` as a defense-in-depth check
        before they reach the subprocess layer.
        """
        if not actions:
            self.exit()
            return

        for name, _action in actions:
            if not PLUGIN_NAME_RE.match(name):
                self._show_error(f"Rejected invalid plugin name: {name!r}")
                self.exit()
                return

        self._pending_actions: list[tuple[str, str]] = list(actions)
        # selected_plugins drives the wizard, integration config chain, and
        # hooks-diff migration — it must be populated from the non-skip
        # actions rather than left over from PluginSelectScreen.
        self.selected_plugins = [name for name, _a in actions]

        self._wizard_screen = WizardScreen(selected_plugins=self.selected_plugins)
        if self._wizard_screen._load_errors:
            from installer.screens.corrupt_yaml import CorruptYamlScreen

            def _after_corrupt_choice(proceed: bool | None) -> None:
                if not proceed:
                    self.run_worker(self._build_status_screen(), exclusive=True)
                    return
                self.push_screen(
                    self._wizard_screen,
                    callback=self._on_wizard_complete,
                )

            self.push_screen(
                CorruptYamlScreen(self._wizard_screen._load_errors),
                callback=_after_corrupt_choice,
            )
            return
        self.push_screen(
            self._wizard_screen,
            callback=self._on_wizard_complete,
        )

    def _on_wizard_complete(self, config: dict[str, Any] | None) -> None:
        """Handle the result from the configuration wizard.

        ``config`` is a flat dotted-key dict produced by ``WizardScreen``
        (merged basic + advanced answers). It is split by ``yaml_file`` and
        round-tripped through ``ProjConfig.from_dict``/``to_dict`` for schema
        validation and raw-key preservation.
        """
        if config is None:
            # User cancelled — go back to plugin status screen
            self.run_worker(self._build_status_screen(), exclusive=True)
            return

        self.wizard_config = config
        expected_mtimes = getattr(
            getattr(self, "_wizard_screen", None), "_existing_mtimes", None
        )
        self._write_config_files(config, expected_mtimes=expected_mtimes)

        # Chain integration config screens for selected plugins
        self._pending_integrations: list[str] = []
        self._integration_results: dict[str, dict[str, str | bool]] = {}
        if "todoist" in self.selected_plugins:
            self._pending_integrations.append("todoist")
        if "trello" in self.selected_plugins:
            self._pending_integrations.append("trello")
        if "jira" in self.selected_plugins:
            self._pending_integrations.append("jira")
        self._push_next_integration()

    def _push_next_integration(self) -> None:
        """Push the next integration config screen, or proceed to install."""
        if not self._pending_integrations:
            # Check hooks diff before proceeding to install
            self._check_hooks_diff()
            return
        service = self._pending_integrations.pop(0)
        self._current_integration = service
        screen_map: dict[str, type[BaseIntegrationScreen]] = {
            "todoist": TodoistConfigScreen,
            "trello": TrelloConfigScreen,
            "jira": JiraConfigScreen,
        }
        self.push_screen(screen_map[service](), callback=self._on_integration_done)

    def _on_integration_done(self, result: dict[str, str | bool] | None) -> None:
        """Handle completion of an integration config screen."""
        # result is dict of config values or None (skipped)
        if result is not None:
            self._integration_results[self._current_integration] = result
        self._push_next_integration()

    def _check_hooks_diff(self) -> None:
        """Compute hooks diff and show review screen if changes exist."""
        from installer.hooks_diff import compute_hooks_diff

        cache_dir = (
            Path.home() / ".claude" / "plugins" / "cache" / "claude-project-manager"
        )
        from installer.wizard import _resolve_plugin_dir

        self._plugin_dirs: list[Path] = []
        for name in self.selected_plugins:
            resolved = _resolve_plugin_dir(cache_dir, name)
            if resolved is not None:
                self._plugin_dirs.append(resolved)

        hooks_path = Path.home() / ".claude" / "hooks.yaml"
        diffs = compute_hooks_diff(hooks_path, self._plugin_dirs)

        if diffs:
            from installer.screens.hooks_diff import HooksDiffScreen

            self._hooks_diffs = diffs
            self.push_screen(
                HooksDiffScreen(self._plugin_dirs, diffs=diffs),
                callback=self._on_hooks_diff_done,
            )
        else:
            self._start_status_install()

    def _on_hooks_diff_done(self, result: dict[str, set[str]] | None) -> None:
        """Handle yaml_hooks diff result, apply selections, proceed to install."""
        if result is not None:
            from installer.hooks_diff import apply_diffs

            hooks_path = Path.home() / ".claude" / "hooks.yaml"
            apply_ids = result.get("apply", set())
            remove_ids = result.get("remove", set())
            if apply_ids or remove_ids:
                apply_diffs(hooks_path, self._hooks_diffs, apply_ids, remove_ids)

        self._start_status_install()

    def _build_install_plan(
        self, actions: list[tuple[str, str]], description: str
    ) -> InstallPlan:
        """Resolve plugin names → IDs and build an InstallPlan.

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
        return InstallPlan(description=description, actions=install_actions)

    def _start_status_install(self) -> None:
        """Build an InstallPlan for ``self._pending_actions`` and exit the app."""
        actions = getattr(self, "_pending_actions", [])
        if not actions:
            self.exit()
            return
        self.install_plan = self._build_install_plan(
            actions,
            description=f"Processing {len(actions)} plugin actions...",
        )
        self.exit()

    def _show_error(self, message: str) -> None:
        """Surface an error to the user via the placeholder Static + log."""
        from textual.css.query import NoMatches

        try:
            placeholder = self.query_one("#placeholder", Static)
            placeholder.update(f"[red]Error:[/red] {message}")
        except NoMatches:
            pass  # placeholder not yet mounted; log.error below still fires
        self.log.error(message)

    def _write_config_files(
        self,
        config: dict[str, Any],
        expected_mtimes: dict[str, float] | None = None,
    ) -> None:
        """Write every ~/.claude/<yaml_file>.yaml touched by wizard answers.

        Uses installer._config_writer to partition answers by bucket, merge
        with preserved unknown keys, normalize, and atomically write with
        fcntl advisory locks and TOCTOU mtime re-check.

        expected_mtimes is the WizardScreen._existing_mtimes dict captured at
        read time; passed through so the writer can detect drift from other
        writers.
        """
        from installer._config_writer import (
            partition_answers_by_bucket,
            write_bucket,
        )

        buckets = partition_answers_by_bucket(config)
        claude_home = Path.home() / ".claude"
        expected_mtimes = expected_mtimes or {}

        for bucket_name, answers in buckets.items():
            if not answers:
                continue
            path = claude_home / f"{bucket_name}.yaml"
            try:
                existing = load_existing_yaml(path)
            except ConfigLoadError as exc:
                self._show_error(f"Failed to load {path}: {exc.original}")
                return
            write_bucket(
                path,
                existing,
                answers,
                bucket=bucket_name,
                expected_mtime=expected_mtimes.get(bucket_name),
            )

        # Ensure managed section in global CLAUDE.md
        ensure_managed_section(Path.home() / ".claude" / "CLAUDE.md")

    # -- Update flow callbacks --

    def _on_update_selected(self, selected: list[str]) -> None:
        """Handle the result from the update selection screen."""
        if not selected or self._state is None:
            self.exit()
            return
        self.selected_plugins = selected
        self.install_plan = self._build_install_plan(
            [(name, "update") for name in selected],
            description="Updating plugins...",
        )
        self.exit()

    # -- Reinstall flow callbacks --

    async def _confirm_orphans(self, orphan_names: list[str]) -> bool:
        """Show ConfirmScreen for orphan removal; returns True if user confirmed."""
        future: asyncio.Future[bool] = asyncio.get_event_loop().create_future()

        def _cb(result: ConfirmResult) -> None:
            if not future.done():
                future.set_result(bool(result.confirmed))

        self.push_screen(
            ConfirmScreen(
                title="Remove Orphaned Plugins",
                message=(
                    f"Found {len(orphan_names)} orphaned plugin dir(s) in cache:\n"
                    f"  {', '.join(orphan_names)}\n\n"
                    "These plugins are no longer in the marketplace. Remove them?"
                ),
                options=[],
                confirm_label="Remove",
                confirm_variant="warning",
            ),
            callback=_cb,
        )
        return await future

    def _on_reinstall_confirmed(self, result: ConfirmResult) -> None:
        """Handle the reinstall confirmation result."""
        if not result.confirmed or self._state is None:
            self.exit()
            return
        reset_configs = result.options.get("reset_configs", False)
        self.run_worker(
            self._prepare_and_reinstall(reset_configs),
            exclusive=True,
        )

    async def _prepare_and_reinstall(self, reset_configs: bool) -> None:
        """Scan/prune stale cache, build InstallPlan for reinstall, exit app."""
        cache_dir = _cache_dir_for_reinstall()
        marketplace_path = _marketplace_path_for_reinstall()

        if cache_dir.is_dir() and marketplace_path.is_file():
            try:
                report = await asyncio.to_thread(
                    scan_stale_cache, cache_dir, marketplace_path
                )
            except (FileNotFoundError, OSError):
                report = None

            if report is not None:
                await asyncio.to_thread(prune_stale_versions, cache_dir, report)
                if report.orphans:
                    if await self._confirm_orphans(report.orphans):
                        await asyncio.to_thread(
                            prune_orphaned_plugins, cache_dir, report.orphans
                        )

        try:
            plugins = await asyncio.to_thread(get_installed_plugins)
        except InstallerError as exc:
            self.reinstall_message = (
                f"[red]✗ Failed to query installed plugins: {exc}[/red]"
            )
            self.exit()
            return
        if not plugins:
            self.reinstall_message = "Nothing to reinstall"
            self.exit()
            return
        # get_installed_plugins() returns qualified IDs; strip to short names for
        # _build_install_plan which handles name→ID resolution internally.
        short_names = [pid.split("@")[0] for pid in plugins]
        self.install_plan = self._build_install_plan(
            [(name, "reinstall") for name in short_names],
            description="Reinstalling plugins...",
        )
        self.exit()

    # -- Uninstall flow callbacks --

    def _on_uninstall_confirmed(self, result: ConfirmResult) -> None:
        """Handle the uninstall confirmation result."""
        if not result.confirmed or self._state is None:
            self.exit()
            return
        self.run_worker(
            self._prepare_and_uninstall(result),
            exclusive=True,
        )

    async def _prepare_and_uninstall(self, result: ConfirmResult) -> None:
        """Build an InstallPlan for uninstall and exit the app."""
        plugins = await asyncio.to_thread(get_installed_plugins)
        if not plugins:
            self.exit()
            return
        self.full_cleanup = result.options.get("full_cleanup", False)
        # get_installed_plugins() returns qualified IDs; strip to short names.
        short_names = [pid.split("@")[0] for pid in plugins]
        self.install_plan = self._build_install_plan(
            [(name, "uninstall") for name in short_names],
            description="Uninstalling plugins...",
        )
        self.exit()

    # -- Shared callbacks --

    def _on_progress_done(self, _result: None) -> None:
        """Handle progress screen completion."""
        from textual.css.query import NoMatches

        try:
            placeholder = self.query_one("#placeholder", Static)
            placeholder.update(f"{self.mode.title()} complete.")
        except NoMatches:
            pass

    def action_back(self) -> None:
        """Go back to previous screen or quit."""
        if len(self.screen_stack) > 1:
            self.pop_screen()
        else:
            self.exit()

    def run(self, **kwargs) -> None:  # type: ignore[override]
        """Run installer TUI, then trigger post-install flat-todo migration check."""
        super().run(**kwargs)

        # Post-install flat-todo migration check (todo 636 Phase 1)
        import sys

        from installer.cli import load_project_list
        from installer.migrations.entry import run_pending_migrations

        _mig_code = run_pending_migrations(
            load_project_list(),
            interactive=sys.stdin.isatty(),
        )
        # Non-zero from migration contributes to overall exit code but doesn't mask plugin errors.
        if _mig_code and not getattr(self, "_exit_code", 0):
            self._exit_code = _mig_code


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
    """Launch a standalone Textual app that drives the migration screens.

    Returns exit code: 0 success, 2 partial, 3 user quit.
    """

    from installer.flow.console import get_console
    from installer.flow.migration_summary import (
        MigrationOutcome,
        show_migration_summary,
    )
    from installer.migrations.flat_todo import FlatTodoMigration
    from installer.screens.migration_overview import MigrationOverviewScreen
    from installer.screens.migration_review import MigrationReviewScreen

    outcomes: list[MigrationOutcome] = []
    _collected_runners: list[FlatTodoMigration] = []
    exit_code = 0

    class MigrationApp(App):
        def on_mount(self) -> None:
            integration_map = _integration_badges(pending, integrations)
            counts = {p.name: _count_parents_children(p) for p in pending}
            self.push_screen(
                MigrationOverviewScreen(
                    pending=pending,
                    integration_map=integration_map,
                    counts=counts,
                ),
                self._after_overview,
            )

        def _after_overview(self, result: tuple) -> None:
            action, _payload = result
            if action in ("skip_all", "quit"):
                nonlocal exit_code
                exit_code = 3 if action == "quit" else 0
                self.exit()
                return
            self._review_next(iter(pending))

        def _review_next(self, it) -> None:
            nonlocal exit_code
            try:
                project = next(it)
            except StopIteration:
                # Summary is rendered post-Textual-exit via show_migration_summary.
                # Textual owns the terminal during the app; Rich output works
                # only after App.run() returns.
                self.exit()
                return

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
                self._review_next(it)
                return

            runner = FlatTodoMigration(
                project=project,
                run_ts=run_ts,
                backup_root=backup_root,
                integrations=integrations,
                strict_resync=strict_resync,
            )
            plan = runner.plan()
            self.push_screen(
                MigrationReviewScreen(
                    plan=plan,
                    backup_preview=str(backup_root / project.name),
                ),
                lambda r, runner=runner, it=it: self._after_review(r, runner, it),
            )

        def _after_review(self, result, runner, it) -> None:
            action, _ = result
            nonlocal exit_code
            if action == "skip":
                runner.confirm(False)
                outcomes.append(
                    MigrationOutcome(
                        project=runner.project.name,
                        ok=True,
                        resync_partial=False,
                        backup="—",
                    ),
                )
                self._review_next(it)
                return
            if action == "quit":
                exit_code = 3
                self.exit()
                return
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
            self._review_next(it)

    MigrationApp().run()
    # Textual has exited; terminal is ours again. Print summary via Rich.
    show_migration_summary(outcomes, get_console())

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
