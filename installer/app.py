"""Textual TUI application for the installer."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import Footer, Static

from installer._config_loader import ConfigLoadError, load_existing_yaml
from installer.cleanup import (
    _cache_dir_for_reinstall,
    _marketplace_path_for_reinstall,
    cleanup_orphaned_plugin_caches,
    prune_orphaned_plugins,
    prune_stale_versions,
    scan_stale_cache,
)
from installer.detect import InstallState, detect_existing
from installer.errors import InstallerError
from installer.plugin_status import (
    PLUGIN_NAME_RE,
    PluginStatus,
    build_plugin_status_list,
)
from installer.screens.confirm import ConfirmOption, ConfirmResult, ConfirmScreen
from installer.screens.detection import DetectionScreen, PluginDetectionRow
from installer.screens.plugin_select import PluginStatusScreen
from installer.screens.integration_config import (
    BaseIntegrationScreen,
    JiraConfigScreen,
    TodoistConfigScreen,
    TrelloConfigScreen,
)
from installer.screens.progress import ProgressScreen
from installer.screens.summary import PluginOutcome, SummaryScreen
from installer.screens.update import UpdateScreen
from installer.screens.wizard import WizardScreen
from installer.plugin_cli import (
    add_marketplace,
    check_marketplace_registered,
    get_available_plugins,
    get_installed_plugins,
    install_plugin,
    remove_marketplace,
    uninstall_plugin,
    update_plugin,
)
from installer.update import (
    _read_installed_version,
    _read_marketplace_versions,
    compare_versions,
)
from claudemd import ensure_managed_section, remove_managed_section

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

    def _start_status_install(self) -> None:
        """Launch the status-driven install worker for ``self._pending_actions``."""
        actions = getattr(self, "_pending_actions", [])
        if not actions:
            self.exit()
            return
        total = len(actions) + 1  # +1 for marketplace check
        progress = ProgressScreen(
            description=f"Processing {len(actions)} plugin actions...",
            total=total,
        )
        self.push_screen(progress, callback=self._on_progress_done)
        self.run_worker(
            self._run_status_install_worker(actions, progress),
            exclusive=True,
        )

    async def _run_status_install_worker(
        self,
        actions: list[tuple[str, str]],
        progress: ProgressScreen,
    ) -> list[PluginOutcome]:
        """Execute each ``(plugin_name, action)`` tuple and return outcomes.

        Dispatches ``install_plugin`` / ``uninstall_plugin`` via
        ``asyncio.to_thread``, catching ``InstallerError`` per plugin so one
        failure doesn't abort the batch. Writes a progress log line per
        action and pushes a ``SummaryScreen`` with the aggregated outcomes.
        """
        await progress.wait_ready()
        branch = self._branch
        outcomes: list[PluginOutcome] = []

        # Marketplace setup — shared prelude
        try:
            progress.write_log("[bold]Checking marketplace...[/bold]")
            registered = await asyncio.to_thread(check_marketplace_registered)
            if not registered:
                branch_msg = f" (branch: {branch})" if branch else ""
                progress.write_log(f"  Adding marketplace...{branch_msg}")
                await asyncio.to_thread(add_marketplace, branch=branch)
                progress.write_log("  [green]Marketplace registered.[/green]")
            elif branch:
                progress.write_log(f"  Re-adding for branch: {branch}")
                await asyncio.to_thread(remove_marketplace)
                await asyncio.to_thread(add_marketplace, branch=branch)
                progress.write_log(f"  [green]Updated to branch {branch}.[/green]")
            else:
                progress.write_log("  [dim]Already registered.[/dim]")
            progress.advance(1, detail="Marketplace ready")
        except InstallerError as exc:
            progress.write_log(f"  [red]Error: {exc}[/red]")
            # Record a synthetic outcome so the summary surfaces the failure.
            outcomes.append(
                PluginOutcome(
                    name="<marketplace>",
                    action="register",
                    status="failed",
                    error=str(exc),
                )
            )
            self._push_summary(outcomes)
            return outcomes

        # Build name→ID map
        try:
            available = await asyncio.to_thread(get_available_plugins)
            installed_ids = await asyncio.to_thread(get_installed_plugins)
        except InstallerError as exc:
            progress.write_log(f"  [red]Error listing plugins: {exc}[/red]")
            outcomes.append(
                PluginOutcome(
                    name="<plugin-list>",
                    action="list",
                    status="failed",
                    error=str(exc),
                )
            )
            self._push_summary(outcomes)
            return outcomes

        name_to_id: dict[str, str] = {}
        for pid in available + installed_ids:
            name = pid.split("@")[0]
            name_to_id.setdefault(name, pid)

        # Dispatch actions
        for plugin_name, action in actions:
            plugin_id = name_to_id.get(
                plugin_name, f"{plugin_name}@claude-project-manager"
            )
            try:
                if action == "install":
                    progress.write_log(f"  Installing {plugin_id}...")
                    await asyncio.to_thread(install_plugin, plugin_id)
                elif action == "reinstall":
                    progress.write_log(f"  Reinstalling {plugin_id}...")
                    await asyncio.to_thread(uninstall_plugin, plugin_id)
                    await asyncio.to_thread(install_plugin, plugin_id)
                elif action == "uninstall":
                    progress.write_log(f"  Uninstalling {plugin_id}...")
                    await asyncio.to_thread(uninstall_plugin, plugin_id)
                else:
                    progress.write_log(
                        f"  [dim]Skipping {plugin_name} ({action})[/dim]"
                    )
                    progress.advance(1, detail=f"Skipped: {plugin_name}")
                    continue
                progress.write_log(f"  [green]✓ {plugin_name} {action}[/green]")
                progress.advance(1, detail=f"{action}: {plugin_name}")
                outcomes.append(
                    PluginOutcome(name=plugin_name, action=action, status="ok")
                )
            except InstallerError as exc:
                progress.write_log(f"  [red]✗ {plugin_name} {action}: {exc}[/red]")
                progress.advance(1, detail=f"Failed: {plugin_name}")
                outcomes.append(
                    PluginOutcome(
                        name=plugin_name,
                        action=action,
                        status="failed",
                        error=str(exc),
                    )
                )

        progress.write_log("[bold]Cleaning up orphan plugin caches...[/bold]")
        cache_root = Path.home() / ".claude" / "plugins" / "cache"
        installed_json = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
        try:
            removed = await asyncio.to_thread(
                cleanup_orphaned_plugin_caches,
                cache_root,
                installed_json,
            )
            if removed:
                for name in removed:
                    progress.write_log(f"  [dim]removed orphan: {name}[/dim]")
            else:
                progress.write_log("  [dim]no orphans found[/dim]")
        except (FileNotFoundError, json.JSONDecodeError, OSError) as exc:
            progress.write_log(f"  [yellow]cleanup skipped: {exc}[/yellow]")
        except Exception:
            logger.exception("Unexpected error during orphan cleanup")

        self._push_summary(outcomes)
        return outcomes

    def _push_summary(self, outcomes: list[PluginOutcome]) -> None:
        """Push the post-install ``SummaryScreen`` on the Textual event loop."""
        self.call_later(self.push_screen, SummaryScreen(outcomes=outcomes))

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
        progress = ProgressScreen(
            description="Updating plugins...", total=len(selected)
        )
        self.push_screen(progress, callback=self._on_progress_done)
        self.run_worker(self._run_update_worker(selected, progress), exclusive=True)

    async def _run_update_worker(
        self, selected: list[str], progress: ProgressScreen
    ) -> None:
        """Execute plugin updates, advancing the progress bar."""
        await progress.wait_ready()
        updated: set[str] = set()
        for plugin_name in selected:
            try:
                progress.write_log(f"  Updating {plugin_name}...")
                await asyncio.to_thread(update_plugin, plugin_name)
                updated.add(plugin_name)
                progress.write_log(f"  [green]✓ {plugin_name} updated[/green]")
                progress.advance(1, detail=f"Updated {plugin_name}")
            except InstallerError as exc:
                progress.write_log(f"  [red]✗ {plugin_name} failed: {exc}[/red]")
                progress.advance(1, detail=f"Failed: {plugin_name}")

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
        """Query authoritative plugin list, push progress screen, run worker."""
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
            progress = ProgressScreen(description="Reinstalling plugins...", total=1)
            self.push_screen(progress, callback=self._on_progress_done)
            await progress.wait_ready()
            progress.write_log(
                f"  [red]✗ Failed to query installed plugins: {exc}[/red]"
            )
            progress.advance(1, detail="Failed")
            return
        if not plugins:
            progress = ProgressScreen(description="Reinstalling plugins...", total=1)
            self.push_screen(progress, callback=self._on_progress_done)
            await progress.wait_ready()
            progress.write_log("  Nothing to reinstall")
            progress.advance(1, detail="Nothing to reinstall")
            return
        progress = ProgressScreen(
            description="Reinstalling plugins...", total=2 + len(plugins)
        )
        self.push_screen(progress, callback=self._on_progress_done)
        await self._run_reinstall_worker(plugins, progress, reset_configs)

    async def _run_reinstall_worker(
        self,
        plugins: list[str],
        progress: ProgressScreen,
        reset_configs: bool,
    ) -> None:
        """Execute plugin reinstalls, advancing the progress bar.

        Phases: remove marketplace → re-add marketplace → install all.
        Removing the marketplace uninstalls all plugins atomically.
        """
        await progress.wait_ready()

        branch = self._branch

        # Phase 1: remove marketplace (uninstalls all plugins atomically)
        try:
            progress.write_log("  [bold]Removing marketplace...[/bold]")
            await asyncio.to_thread(remove_marketplace)
            progress.write_log("  [green]✓ Marketplace removed[/green]")
            progress.advance(1, detail="Marketplace removed")
        except InstallerError as exc:
            progress.write_log(f"  [red]✗ Failed to remove marketplace: {exc}[/red]")
            progress.advance(1, detail="Marketplace removal failed")
            return

        # Phase 2: re-add marketplace
        try:
            branch_msg = f" (branch: {branch})" if branch else ""
            progress.write_log(f"  [bold]Re-adding marketplace{branch_msg}...[/bold]")
            await asyncio.to_thread(add_marketplace, branch=branch)
            progress.write_log(f"  [green]✓ Marketplace re-added{branch_msg}[/green]")
            progress.advance(1, detail="Marketplace re-added")
        except InstallerError as exc:
            progress.write_log(f"  [red]✗ Failed to re-add marketplace: {exc}[/red]")
            progress.advance(1, detail="Marketplace re-add failed")
            return

        # Phase 3: install all plugins
        reinstalled: set[str] = set()
        for plugin_name in plugins:
            try:
                progress.write_log(f"  Installing {plugin_name}...")
                await asyncio.to_thread(install_plugin, plugin_name)
                reinstalled.add(plugin_name)
                progress.write_log(f"  [green]✓ {plugin_name} reinstalled[/green]")
                progress.advance(1, detail=f"Reinstalled {plugin_name}")
            except InstallerError as exc:
                progress.write_log(f"  [red]✗ {plugin_name} failed: {exc}[/red]")
                progress.advance(1, detail=f"Failed: {plugin_name}")

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
        """Fetch installed plugins off-thread, then run the uninstall worker."""
        plugins = await asyncio.to_thread(get_installed_plugins)
        if not plugins:
            self.exit()
            return
        full_cleanup = result.options.get("full_cleanup", False)
        progress = ProgressScreen(description="Uninstalling plugins...", total=1)
        self.push_screen(progress, callback=self._on_progress_done)
        await self._run_uninstall_worker(plugins, progress, full_cleanup)

    async def _run_uninstall_worker(
        self,
        plugins: list[str],
        progress: ProgressScreen,
        full_cleanup: bool,
    ) -> None:
        """Execute plugin removal by removing the marketplace atomically."""
        await progress.wait_ready()

        try:
            progress.write_log(
                f"  [bold]Removing marketplace ({len(plugins)} plugins)...[/bold]"
            )
            await asyncio.to_thread(remove_marketplace)
            progress.write_log(
                f"  [green]✓ Marketplace removed — {len(plugins)} plugins uninstalled[/green]"
            )
            progress.advance(1, detail=f"Removed {len(plugins)} plugins")
        except InstallerError as exc:
            progress.write_log(f"  [red]✗ Failed to remove marketplace: {exc}[/red]")
            progress.advance(1, detail="Failed")

        if full_cleanup:
            claude_md = Path.home() / ".claude" / "CLAUDE.md"
            if remove_managed_section(claude_md):
                progress.write_log(
                    "  [green]✓ Removed managed section from CLAUDE.md[/green]"
                )
            else:
                progress.write_log("  [dim]No managed section in CLAUDE.md[/dim]")

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
