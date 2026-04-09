"""Detection screen showing installed plugin state."""

from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Static

from installer.detect import InstallState, _safe_stat, _validate_yaml


@dataclass
class PluginDetectionRow:
    """A row in the detection table."""

    plugin: str
    installed_version: str | None
    available_version: str | None

    @property
    def status(self) -> str:
        if self.installed_version is None:
            return "not installed"
        if self.available_version is None:
            return "unknown"
        if self.installed_version == self.available_version:
            return "up-to-date"
        return "outdated"


class DetectionScreen(Screen[bool]):
    """Display installed plugin state in a styled DataTable.

    Shows plugin versions, statuses (up-to-date/outdated/not installed),
    and installation component paths.

    Dismisses with ``True`` to continue or ``False`` to cancel.
    """

    CSS = """
    DetectionScreen {
        layout: vertical;
    }

    #detection-title {
        dock: top;
        height: 3;
        content-align: center middle;
        text-style: bold;
        color: $text;
        background: $accent;
        padding: 1 2;
    }

    #components-container {
        height: auto;
        max-height: 10;
        margin: 1 2 1 2;
        padding: 1 2;
        border: round $primary-background;
        background: $surface;
    }

    #table-container {
        height: 1fr;
        margin: 0 2;
        border: round $primary-background;
    }

    DataTable {
        height: 1fr;
    }

    #summary-bar {
        dock: bottom;
        height: auto;
        max-height: 3;
        padding: 0 2;
        color: $accent;
        background: $surface;
        text-style: italic;
    }

    #detection-button-bar {
        dock: bottom;
        height: 3;
        align: center middle;
        padding: 0 2;
    }

    #detection-button-bar Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("enter", "continue_action", "Continue", show=True),
        Binding("q", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        state: InstallState,
        plugin_rows: list[PluginDetectionRow],
        title_text: str = "Existing Installation",
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._state = state
        self._plugin_rows = plugin_rows
        self._title_text = title_text

    def compose(self) -> ComposeResult:
        yield Static(self._title_text, id="detection-title")
        yield Static("", id="components-container")
        with Vertical(id="table-container"):
            yield DataTable(id="detection-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="summary-bar")
        with Horizontal(id="detection-button-bar"):
            yield Button("Continue", variant="primary", id="btn-continue")
            yield Button("Cancel", variant="default", id="btn-cancel")
        yield Footer()

    def on_mount(self) -> None:
        """Populate components info and plugin table."""
        self._populate_components()
        self._populate_table()
        self._update_summary()

    def _populate_components(self) -> None:
        """Show detected installation components."""
        state = self._state
        lines: list[str] = []

        items: list[tuple[str, object]] = [
            ("proj.yaml", state.proj_yaml),
            ("worktree.yaml", state.worktree_yaml),
            ("settings.json", state.settings_json),
            ("Marketplace dir", state.marketplace_dir),
            ("Cache dir", state.cache_dir),
        ]

        for label, path in items:
            if path is None:
                lines.append(f"  {label}: not found")
            else:
                mtime = _safe_stat(path)
                mtime_str = mtime.strftime("%Y-%m-%d %H:%M") if mtime else "unknown"
                valid = True
                if hasattr(path, "suffix") and path.suffix in (".yaml", ".yml"):
                    valid = _validate_yaml(path)
                status = "found" if valid else "empty/malformed"
                lines.append(f"  {label}: {status} ({mtime_str})")

        if state.mcp_entries:
            lines.append(f"  MCP entries: {', '.join(state.mcp_entries)}")

        container = self.query_one("#components-container", Static)
        container.update("\n".join(lines))

    def _populate_table(self) -> None:
        """Fill the DataTable with plugin detection rows."""
        table = self.query_one("#detection-table", DataTable)
        table.add_columns("Plugin", "Installed", "Available", "Status")

        _STATUS_STYLES = {
            "up-to-date": ("green", "bold"),
            "outdated": ("yellow", "bold"),
            "not installed": ("red", ""),
            "unknown": ("dim", "italic"),
        }

        for row in self._plugin_rows:
            installed = row.installed_version or "-"
            available = row.available_version or "-"
            status = row.status
            color, style = _STATUS_STYLES.get(status, ("", ""))
            styled_status = Text(status, style=f"{color} {style}".strip())

            table.add_row(
                row.plugin,
                installed,
                available,
                styled_status,
                key=f"detect-{row.plugin}",
            )

    def _update_summary(self) -> None:
        """Update the summary bar with counts."""
        up_to_date = sum(1 for r in self._plugin_rows if r.status == "up-to-date")
        outdated = sum(1 for r in self._plugin_rows if r.status == "outdated")
        not_installed = sum(1 for r in self._plugin_rows if r.status == "not installed")

        parts: list[str] = []
        if up_to_date:
            parts.append(f"{up_to_date} up-to-date")
        if outdated:
            parts.append(f"{outdated} outdated")
        if not_installed:
            parts.append(f"{not_installed} not installed")

        summary = self.query_one("#summary-bar", Static)
        summary.update(" | ".join(parts) if parts else "No plugins detected")

    def action_continue_action(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-continue":
            self.dismiss(True)
        elif event.button.id == "btn-cancel":
            self.dismiss(False)
