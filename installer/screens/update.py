"""Update screen for selecting outdated plugins to update."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

# Checkbox symbols
_CHECKED = "\u2611"  # ☑
_UNCHECKED = "\u2610"  # ☐


class UpdateScreen(Screen[list[str]]):
    """Select which outdated plugins to update.

    Displays a DataTable with checkboxes showing current -> new version.
    Dismisses with a list of selected plugin names.

    Args:
        version_diffs: Dict of plugin_name -> (installed_version, available_version).
    """

    CSS = """
    UpdateScreen {
        layout: vertical;
    }

    #update-title {
        dock: top;
        height: 3;
        content-align: center middle;
        text-style: bold;
        color: $accent;
        padding: 1 2;
    }

    #update-table-container {
        height: 1fr;
        margin: 0 2;
    }

    DataTable {
        height: 1fr;
    }

    #update-status {
        dock: bottom;
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }

    #update-button-bar {
        dock: bottom;
        height: 3;
        align: center middle;
        padding: 0 2;
    }

    #update-button-bar Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("space", "toggle_row", "Toggle", show=True),
        Binding("enter", "update_selected", "Update Selected", show=True),
        Binding("a", "select_all", "All", show=True),
        Binding("n", "select_none", "None", show=True),
        Binding("q", "cancel", "Cancel", show=True),
    ]

    def __init__(
        self,
        version_diffs: dict[str, tuple[str, str]],
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._diffs = version_diffs
        self._plugins = sorted(version_diffs.keys())
        self._selected: set[str] = set(self._plugins)  # All selected by default
        self._row_index: dict[int, str] = {}  # row_idx -> plugin_name

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Plugin Updates Available", id="update-title")
        with Vertical(id="update-table-container"):
            yield DataTable(id="update-table", cursor_type="row", zebra_stripes=True)
        yield Static("", id="update-status")
        with Horizontal(id="update-button-bar"):
            yield Button("Update Selected", variant="primary", id="btn-update-selected")
            yield Button("Update All", variant="success", id="btn-update-all")
            yield Button("Cancel", variant="default", id="btn-update-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self._populate_table()
        self._update_status()

    def _populate_table(self) -> None:
        """Fill the table with outdated plugin rows."""
        table = self.query_one("#update-table", DataTable)
        table.add_columns(" ", "Plugin", "Installed", "", "Available")

        for idx, plugin_name in enumerate(self._plugins):
            old_ver, new_ver = self._diffs[plugin_name]
            checked = _CHECKED if plugin_name in self._selected else _UNCHECKED
            table.add_row(
                checked,
                plugin_name,
                old_ver,
                "->",
                new_ver,
                key=f"update-{plugin_name}",
            )
            self._row_index[idx] = plugin_name

    def _update_row_checkbox(self, plugin_name: str) -> None:
        """Update the checkbox cell for a plugin row."""
        table = self.query_one("#update-table", DataTable)
        row_key = f"update-{plugin_name}"
        checked = _CHECKED if plugin_name in self._selected else _UNCHECKED
        col_key = table.ordered_columns[0].key
        table.update_cell(row_key, col_key, checked)

    def _update_status(self) -> None:
        """Update the status bar with selection count."""
        total = len(self._plugins)
        selected = len(self._selected)
        status = self.query_one("#update-status", Static)
        status.update(f"{selected}/{total} plugins selected for update")

    def _toggle_plugin(self, plugin_name: str) -> None:
        if plugin_name in self._selected:
            self._selected.discard(plugin_name)
        else:
            self._selected.add(plugin_name)
        self._update_row_checkbox(plugin_name)
        self._update_status()

    def _get_current_plugin(self) -> str | None:
        table = self.query_one("#update-table", DataTable)
        return self._row_index.get(table.cursor_row)

    # -- Actions --

    def action_toggle_row(self) -> None:
        plugin_name = self._get_current_plugin()
        if plugin_name:
            self._toggle_plugin(plugin_name)

    def action_update_selected(self) -> None:
        result = [p for p in self._plugins if p in self._selected]
        self.dismiss(result)

    def action_select_all(self) -> None:
        for plugin_name in self._plugins:
            self._selected.add(plugin_name)
            self._update_row_checkbox(plugin_name)
        self._update_status()

    def action_select_none(self) -> None:
        for plugin_name in self._plugins:
            self._selected.discard(plugin_name)
            self._update_row_checkbox(plugin_name)
        self._update_status()

    def action_cancel(self) -> None:
        self.dismiss([])

    # -- Event handlers --

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        plugin_name = self._row_index.get(event.cursor_row)
        if plugin_name:
            self._toggle_plugin(plugin_name)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-update-selected":
            self.action_update_selected()
        elif event.button.id == "btn-update-all":
            self._selected = set(self._plugins)
            result = list(self._plugins)
            self.dismiss(result)
        elif event.button.id == "btn-update-cancel":
            self.dismiss([])
