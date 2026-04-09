"""Textual TUI application for the installer."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Footer, Static

from installer.detect import InstallState, detect_existing
from installer.errors import InstallerError
from installer.screens.confirm import ConfirmOption, ConfirmResult, ConfirmScreen
from installer.screens.detection import DetectionScreen, PluginDetectionRow
from installer.screens.plugin_select import PluginSelectScreen
from installer.screens.integration_config import (
    BaseIntegrationScreen,
    JiraConfigScreen,
    TodoistConfigScreen,
    TrelloConfigScreen,
)
from installer.screens.progress import ProgressScreen
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
from installer.claudemd import ensure_managed_section, remove_managed_section
from installer.wizard import _atomic_write, _yaml_line


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
    _PROJ_PLUGINS = {"proj", "hooks", "sandbox", "todoist", "trello", "jira"}

    def __init__(self, mode: str = "install", args: object = None) -> None:
        super().__init__()
        self.mode = mode  # install, update, reinstall, uninstall
        self.installer_args = args
        self.selected_plugins: list[str] = []
        self.wizard_config: dict[str, str | bool] | None = None
        self._state: InstallState | None = None
        self._branch: str | None = getattr(args, "branch", None) if args else None

    def compose(self) -> ComposeResult:
        yield Static(f"Mode: {self.mode}", id="placeholder")
        yield Footer()

    def on_mount(self) -> None:
        """Route to the appropriate screen based on mode."""
        if self.mode == "install":
            self.push_screen(
                PluginSelectScreen(branch=self._branch),
                callback=self._on_plugins_selected,
            )
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

    def _on_plugins_selected(self, selected: list[str]) -> None:
        """Handle the result from the plugin selection screen."""
        self.selected_plugins = selected
        if not selected:
            self.exit()
            return
        # Push configuration wizard
        self.push_screen(
            WizardScreen(selected_plugins=selected),
            callback=self._on_wizard_complete,
        )

    def _on_wizard_complete(self, config: dict[str, str | bool] | None) -> None:
        """Handle the result from the configuration wizard."""
        if config is None:
            # User cancelled — go back to plugin selection
            self.push_screen(
                PluginSelectScreen(branch=self._branch),
                callback=self._on_plugins_selected,
            )
            return

        self.wizard_config = config
        self._write_config_files(config)

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
        plugin_dirs = [
            cache_dir / name
            for name in self.selected_plugins
            if (cache_dir / name).is_dir()
        ]

        hooks_path = Path.home() / ".claude" / "hooks.yaml"
        diffs = compute_hooks_diff(hooks_path, plugin_dirs)

        if diffs:
            from installer.screens.hooks_diff import HooksDiffScreen

            self._hooks_diffs = diffs
            self.push_screen(
                HooksDiffScreen(diffs=diffs), callback=self._on_hooks_diff_done
            )
        else:
            self.run_worker(self._detect_and_route_install(), exclusive=True)

    def _on_hooks_diff_done(self, result: dict[str, set[str]] | None) -> None:
        """Handle hooks diff screen result, apply selections, proceed to install."""
        if result is not None:
            from installer.hooks_diff import apply_diffs

            hooks_path = Path.home() / ".claude" / "hooks.yaml"
            apply_ids = result.get("apply", set())
            remove_ids = result.get("remove", set())
            if apply_ids or remove_ids:
                apply_diffs(hooks_path, self._hooks_diffs, apply_ids, remove_ids)

        self.run_worker(self._detect_and_route_install(), exclusive=True)

    async def _detect_and_route_install(self) -> None:
        """Check installed plugins and route to appropriate install flow."""
        registered = await asyncio.to_thread(check_marketplace_registered)
        installed_ids = (
            await asyncio.to_thread(get_installed_plugins) if registered else []
        )
        installed_names = {pid.split("@")[0] for pid in installed_ids}

        selected = set(self.selected_plugins)
        already = selected & installed_names
        missing = selected - installed_names

        if already and not missing:
            # All selected plugins already installed — ask reinstall or exit
            self.app.call_later(self._show_all_installed_prompt, sorted(already))
        elif already and missing:
            # Some installed, some missing — install only missing
            self.app.call_later(
                self._start_install_missing, sorted(missing), sorted(already)
            )
        else:
            # Nothing installed — fresh install all
            self.app.call_later(self._start_install_all)

    def _show_all_installed_prompt(self, already: list[str]) -> None:
        """All selected plugins are already installed — ask user what to do."""
        self.push_screen(
            ConfirmScreen(
                title="All Plugins Already Installed",
                message=(
                    f"All selected plugins are already installed:\n"
                    f"{', '.join(already)}\n\n"
                    f"Reinstall them? (remove marketplace + re-add + install)"
                ),
                confirm_label="Reinstall",
                cancel_label="Exit",
            ),
            callback=self._on_all_installed_choice,
        )

    def _on_all_installed_choice(self, result: ConfirmResult) -> None:
        """Handle reinstall-all or exit choice."""
        if not result.confirmed:
            self.exit()
            return
        self._reinstall_marketplace = True
        self._start_install_all()

    def _start_install_missing(self, missing: list[str], already: list[str]) -> None:
        """Install only missing plugins."""
        total = len(missing) + 1  # +1 for marketplace check
        progress = ProgressScreen(
            description=f"Installing {len(missing)} missing plugins...",
            total=total,
        )
        self.push_screen(progress, callback=self._on_progress_done)
        self.run_worker(
            self._run_install_worker(missing, progress, skip_installed=True),
            exclusive=True,
        )

    def _start_install_all(self) -> None:
        """Install (or reinstall) all selected plugins."""
        progress = ProgressScreen(
            description="Installing plugins...",
            total=len(self.selected_plugins) + 1,
        )
        self.push_screen(progress, callback=self._on_progress_done)
        reinstall = getattr(self, "_reinstall_marketplace", False)
        self.run_worker(
            self._run_install_worker(
                list(self.selected_plugins),
                progress,
                force_reinstall_marketplace=reinstall,
            ),
            exclusive=True,
        )

    async def _run_install_worker(
        self,
        plugins: list[str],
        progress: ProgressScreen,
        skip_installed: bool = False,
        force_reinstall_marketplace: bool = False,
    ) -> None:
        """Register marketplace and install each selected plugin."""
        await progress.wait_ready()
        branch = self._branch

        # Marketplace setup
        try:
            progress.log("[bold]Checking marketplace...[/bold]")
            if force_reinstall_marketplace:
                progress.log("  Removing and re-adding marketplace...")
                await asyncio.to_thread(remove_marketplace)
                await asyncio.to_thread(add_marketplace, branch=branch)
                progress.log("  [green]Marketplace reinstalled.[/green]")
            else:
                registered = await asyncio.to_thread(check_marketplace_registered)
                if not registered:
                    branch_msg = f" (branch: {branch})" if branch else ""
                    progress.log(f"  Adding marketplace...{branch_msg}")
                    await asyncio.to_thread(add_marketplace, branch=branch)
                    progress.log("  [green]Marketplace registered.[/green]")
                elif branch:
                    progress.log(f"  Re-adding for branch: {branch}")
                    await asyncio.to_thread(remove_marketplace)
                    await asyncio.to_thread(add_marketplace, branch=branch)
                    progress.log(f"  [green]Updated to branch {branch}.[/green]")
                else:
                    progress.log("  [dim]Already registered.[/dim]")
            progress.advance(1, detail="Marketplace ready")
        except InstallerError as exc:
            progress.log(f"  [red]Error: {exc}[/red]")
            return

        # Build name→ID map
        progress.log("[bold]Discovering plugins...[/bold]")
        available = await asyncio.to_thread(get_available_plugins)
        installed_ids = await asyncio.to_thread(get_installed_plugins)
        name_to_id: dict[str, str] = {}
        for pid in available + installed_ids:
            name = pid.split("@")[0]
            name_to_id.setdefault(name, pid)
        installed_names = {pid.split("@")[0] for pid in installed_ids}
        progress.log(f"  {len(available)} available, {len(installed_ids)} installed")

        # Install plugins
        done: set[str] = set()
        for plugin_name in plugins:
            plugin_id = name_to_id.get(plugin_name)
            if plugin_id is None:
                progress.log(f"  [red]✗ {plugin_name} not found[/red]")
                progress.advance(1, detail=f"Skipped: {plugin_name}")
                continue

            if skip_installed and plugin_name in installed_names:
                progress.log(f"  [dim]✓ {plugin_name} already installed[/dim]")
                progress.advance(1, detail=f"Skipped: {plugin_name}")
                continue

            try:
                if plugin_name in installed_names:
                    progress.log(f"  Uninstalling {plugin_name}...")
                    await asyncio.to_thread(uninstall_plugin, plugin_id)
                progress.log(f"  Installing {plugin_id}...")
                await asyncio.to_thread(install_plugin, plugin_id)
                done.add(plugin_name)
                progress.log(f"  [green]✓ {plugin_name} installed[/green]")
                progress.advance(1, detail=f"Installed {plugin_name}")
            except InstallerError as exc:
                progress.log(f"  [red]✗ {plugin_name}: {exc}[/red]")
                progress.advance(1, detail=f"Failed: {plugin_name}")

    def _write_config_files(self, config: dict[str, str | bool]) -> None:
        """Write proj.yaml and/or worktree.yaml from wizard config values."""
        needs_proj = bool(self._PROJ_PLUGINS & set(self.selected_plugins))
        needs_worktree = "worktree" in self.selected_plugins

        if needs_proj:
            proj_yaml = Path.home() / ".claude" / "proj.yaml"
            lines = [
                _yaml_line("version", "1"),
                _yaml_line("tracking_dir", str(config["tracking_dir"])),
                _yaml_line("projects_base_dir", str(config["projects_base_dir"])),
                _yaml_line("sandbox_integration", bool(config["sandbox_integration"])),
                _yaml_line("zoxide_integration", bool(config["zoxide_integration"])),
            ]

            # Integration fields (nested under sync:/jira:)
            todoist_on = config.get("todoist_enabled", False)
            trello_on = config.get("trello_enabled", False)
            jira_on = config.get("jira_enabled", False)

            if todoist_on or trello_on:
                lines.append("sync:\n")
                if todoist_on:
                    lines.append("  todoist:\n")
                    lines.append("    enabled: true\n")
                    lines.append("    auto_sync: true\n")
                if trello_on:
                    lines.append("  trello:\n")
                    lines.append("    enabled: true\n")
                    lines.append("    auto_sync: true\n")
                    board_id = str(config.get("trello_board_id", "")).strip()
                    if board_id:
                        lines.append(f"    default_board_id: {board_id}\n")

            if jira_on:
                lines.append("jira:\n")
                lines.append("  enabled: true\n")
                lines.append("  auto_sync: true\n")
                default_user = str(config.get("jira_default_user", "")).strip()
                if default_user:
                    lines.append(f"  default_user: {default_user}\n")

            _atomic_write(proj_yaml, "".join(lines))

        if needs_worktree:
            wt_yaml = Path.home() / ".claude" / "worktree.yaml"
            lines = [
                _yaml_line("version", "1"),
                _yaml_line("default_worktree_dir", str(config["worktree_dir"])),
            ]
            _atomic_write(wt_yaml, "".join(lines))

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
                progress.log(f"  Updating {plugin_name}...")
                await asyncio.to_thread(update_plugin, plugin_name)
                updated.add(plugin_name)
                progress.log(f"  [green]✓ {plugin_name} updated[/green]")
                progress.advance(1, detail=f"Updated {plugin_name}")
            except InstallerError as exc:
                progress.log(f"  [red]✗ {plugin_name} failed: {exc}[/red]")
                progress.advance(1, detail=f"Failed: {plugin_name}")

    # -- Reinstall flow callbacks --

    def _on_reinstall_confirmed(self, result: ConfirmResult) -> None:
        """Handle the reinstall confirmation result."""
        if not result.confirmed or self._state is None:
            self.exit()
            return
        plugins = self._state.installed_plugins
        if not plugins:
            self.exit()
            return
        progress = ProgressScreen(
            description="Reinstalling plugins...", total=len(plugins)
        )
        self.push_screen(progress, callback=self._on_progress_done)
        reset_configs = result.options.get("reset_configs", False)
        self.run_worker(
            self._run_reinstall_worker(plugins, progress, reset_configs),
            exclusive=True,
        )

    async def _run_reinstall_worker(
        self,
        plugins: list[str],
        progress: ProgressScreen,
        reset_configs: bool,
    ) -> None:
        """Execute plugin reinstalls, advancing the progress bar."""
        await progress.wait_ready()
        reinstalled: set[str] = set()
        for plugin_name in plugins:
            try:
                progress.log(f"  Uninstalling {plugin_name}...")
                await asyncio.to_thread(uninstall_plugin, plugin_name)
                progress.log(f"  Installing {plugin_name}...")
                await asyncio.to_thread(install_plugin, plugin_name)
                reinstalled.add(plugin_name)
                progress.log(f"  [green]✓ {plugin_name} reinstalled[/green]")
                progress.advance(1, detail=f"Reinstalled {plugin_name}")
            except InstallerError as exc:
                progress.log(f"  [red]✗ {plugin_name} failed: {exc}[/red]")
                progress.advance(1, detail=f"Failed: {plugin_name}")

    # -- Uninstall flow callbacks --

    def _on_uninstall_confirmed(self, result: ConfirmResult) -> None:
        """Handle the uninstall confirmation result."""
        if not result.confirmed or self._state is None:
            self.exit()
            return
        plugins = self._state.installed_plugins
        if not plugins:
            self.exit()
            return
        full_cleanup = result.options.get("full_cleanup", False)
        progress = ProgressScreen(
            description="Uninstalling plugins...", total=len(plugins)
        )
        self.push_screen(progress, callback=self._on_progress_done)
        self.run_worker(
            self._run_uninstall_worker(plugins, progress, full_cleanup),
            exclusive=True,
        )

    async def _run_uninstall_worker(
        self,
        plugins: list[str],
        progress: ProgressScreen,
        full_cleanup: bool,
    ) -> None:
        """Execute plugin removal, advancing the progress bar."""
        await progress.wait_ready()
        removed: set[str] = set()
        for plugin_name in plugins:
            try:
                progress.log(f"  Uninstalling {plugin_name}...")
                await asyncio.to_thread(uninstall_plugin, plugin_name)
                removed.add(plugin_name)
                progress.log(f"  [green]✓ {plugin_name} removed[/green]")
                progress.advance(1, detail=f"Removed {plugin_name}")
            except InstallerError as exc:
                progress.log(f"  [red]✗ {plugin_name} failed: {exc}[/red]")
                progress.advance(1, detail=f"Failed: {plugin_name}")

        if full_cleanup:
            claude_md = Path.home() / ".claude" / "CLAUDE.md"
            if remove_managed_section(claude_md):
                progress.log(
                    "  [green]✓ Removed managed section from CLAUDE.md[/green]"
                )
            else:
                progress.log("  [dim]No managed section in CLAUDE.md[/dim]")

    # -- Shared callbacks --

    def _on_progress_done(self, _result: None) -> None:
        """Handle progress screen completion."""
        placeholder = self.query_one("#placeholder", Static)
        placeholder.update(f"{self.mode.title()} complete.")

    def action_back(self) -> None:
        """Go back to previous screen or quit."""
        if len(self.screen_stack) > 1:
            self.pop_screen()
        else:
            self.exit()
