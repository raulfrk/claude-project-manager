"""Textual TUI application for the installer."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.widgets import Footer, Header, Static

from installer.detect import InstallState, detect_existing
from installer.screens.confirm import ConfirmOption, ConfirmResult, ConfirmScreen
from installer.screens.detection import DetectionScreen, PluginDetectionRow
from installer.screens.plugin_select import PluginSelectScreen
from installer.screens.progress import ProgressScreen
from installer.screens.update import UpdateScreen
from installer.screens.wizard import WizardScreen
from installer.uninstall import remove_plugins
from installer.update import (
    _read_installed_version,
    _read_marketplace_versions,
    compare_versions,
    run_update,
)
from installer.wizard import _atomic_write, _yaml_line


class InstallerApp(App):
    """Claude Project Manager installer TUI."""

    CSS = """
    Screen {
        align: center middle;
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

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static(f"Mode: {self.mode}", id="placeholder")
        yield Footer()

    def on_mount(self) -> None:
        """Route to the appropriate screen based on mode."""
        if self.mode == "install":
            self.push_screen(PluginSelectScreen(), callback=self._on_plugins_selected)
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
            self.push_screen(PluginSelectScreen(), callback=self._on_plugins_selected)
            return

        self.wizard_config = config
        self._write_config_files(config)

        placeholder = self.query_one("#placeholder", Static)
        placeholder.update(
            f"Selected: {', '.join(self.selected_plugins)} | Config saved"
        )

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
            _atomic_write(proj_yaml, "".join(lines))

        if needs_worktree:
            wt_yaml = Path.home() / ".claude" / "worktree.yaml"
            lines = [
                _yaml_line("version", "1"),
                _yaml_line("default_worktree_dir", str(config["worktree_dir"])),
            ]
            _atomic_write(wt_yaml, "".join(lines))

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
        if self._state is None:
            return
        for plugin_name in selected:
            run_update([plugin_name], self._state)
            progress.advance(1, detail=f"Updated {plugin_name}")

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
        if self._state is None:
            return
        for plugin_name in plugins:
            run_update([plugin_name], self._state)
            progress.advance(1, detail=f"Reinstalled {plugin_name}")

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
        if self._state is None:
            return
        for plugin_name in plugins:
            remove_plugins([plugin_name], self._state)
            progress.advance(1, detail=f"Removed {plugin_name}")

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
