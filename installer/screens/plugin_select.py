"""Plugin selection screen using Textual DataTable with category grouping."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Header, Static

from installer.tui import (
    CATEGORY_ORDER,
    DEFAULT_PRESELECT,
    PluginInfo,
    load_plugins,
)

# Symbols for checkbox display
_CHECKED = "\u2611"  # ☑
_UNCHECKED = "\u2610"  # ☐


class PluginSelectScreen(Screen[list[str]]):
    """Interactive plugin selection with checkboxes grouped by category.

    Returns a list of selected plugin names via ``dismiss()``.
    """

    CSS = """
    PluginSelectScreen {
        layout: vertical;
    }

    #title-bar {
        dock: top;
        height: 3;
        content-align: center middle;
        text-style: bold;
        color: $accent;
        padding: 1 2;
    }

    #table-container {
        height: 1fr;
        margin: 0 2;
    }

    DataTable {
        height: 1fr;
    }

    #warning-bar {
        dock: bottom;
        height: auto;
        max-height: 3;
        padding: 0 2;
        color: $warning;
        display: none;
    }

    #button-bar {
        dock: bottom;
        height: 3;
        align: center middle;
        padding: 0 2;
    }

    #button-bar Button {
        margin: 0 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        padding: 0 2;
        color: $text-muted;
    }
    """

    BINDINGS = [
        Binding("space", "toggle_row", "Toggle", show=True),
        Binding("enter", "confirm", "Confirm", show=True),
        Binding("a", "select_all", "All", show=True),
        Binding("n", "select_none", "None", show=True),
        Binding("q", "quit_screen", "Quit", show=True),
    ]

    def __init__(
        self,
        marketplace_path: Path | None = None,
        preselect: set[str] | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._marketplace_path = marketplace_path
        self._preselect = preselect if preselect is not None else DEFAULT_PRESELECT
        self._plugins: list[PluginInfo] = []
        # Map row index (0-based, skipping category rows) -> plugin name
        self._row_plugin: dict[int, str] = {}
        # Set of selected plugin names
        self._selected: set[str] = set()
        # Row keys for category separator rows (not selectable)
        self._category_rows: set[int] = set()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Static("Select plugins to install", id="title-bar")
        with Vertical(id="table-container"):
            table = DataTable(id="plugin-table", cursor_type="row", zebra_stripes=True)
            yield table
        yield Static("", id="warning-bar")
        yield Static("", id="status-bar")
        with Horizontal(id="button-bar"):
            yield Button("Confirm", variant="primary", id="btn-confirm")
            yield Button("Cancel", variant="default", id="btn-cancel")
        yield Footer()

    def on_mount(self) -> None:
        """Load plugins and populate the table."""
        self._plugins = load_plugins(self._marketplace_path)
        self._selected = {p.name for p in self._plugins if p.name in self._preselect}
        self._populate_table()
        self._update_status()

    def _populate_table(self) -> None:
        """Fill the DataTable with category headers and plugin rows."""
        table = self.query_one("#plugin-table", DataTable)
        table.add_columns(" ", "Plugin", "Version", "Description", "Default")

        current_category = ""
        row_idx = 0

        for plugin in self._plugins:
            if plugin.category != current_category:
                current_category = plugin.category
                cat_label = next(
                    (label for cat, label in CATEGORY_ORDER if cat == current_category),
                    current_category.title(),
                )
                # Category separator row
                table.add_row(
                    "",
                    f"── {cat_label} ──",
                    "",
                    "",
                    "",
                    key=f"cat-{current_category}",
                )
                self._category_rows.add(row_idx)
                row_idx += 1

            checked = _CHECKED if plugin.name in self._selected else _UNCHECKED
            default_mark = "*" if plugin.name in self._preselect else ""
            table.add_row(
                checked,
                plugin.name,
                plugin.version,
                plugin.description,
                default_mark,
                key=f"plugin-{plugin.name}",
            )
            self._row_plugin[row_idx] = plugin.name
            row_idx += 1

    def _update_row_checkbox(self, plugin_name: str) -> None:
        """Update the checkbox cell for a specific plugin row."""
        table = self.query_one("#plugin-table", DataTable)
        row_key = f"plugin-{plugin_name}"
        checked = _CHECKED if plugin_name in self._selected else _UNCHECKED
        col_key = table.ordered_columns[0].key
        table.update_cell(row_key, col_key, checked)

    def _update_status(self) -> None:
        """Update the status bar with selection count."""
        total = len(self._plugins)
        selected = len(self._selected)
        status = self.query_one("#status-bar", Static)
        status.update(f"{selected}/{total} plugins selected")
        self._check_dependency_warnings()

    def _check_dependency_warnings(self) -> None:
        """Show warning if hooks is deselected but dependents are selected."""
        warning_bar = self.query_one("#warning-bar", Static)
        if "hooks" not in self._selected:
            dependents = [n for n in self._selected if n not in ("hooks", "analyse")]
            if dependents:
                warning_bar.update(
                    f"Warning: hooks not selected but recommended for: "
                    f"{', '.join(sorted(dependents))}. "
                    f"Hook dispatch will be disabled."
                )
                warning_bar.styles.display = "block"
                return
        warning_bar.update("")
        warning_bar.styles.display = "none"

    def _toggle_plugin(self, plugin_name: str) -> None:
        """Toggle selection state for a plugin."""
        if plugin_name in self._selected:
            self._selected.discard(plugin_name)
        else:
            self._selected.add(plugin_name)
        self._update_row_checkbox(plugin_name)
        self._update_status()

    def _get_current_plugin(self) -> str | None:
        """Get the plugin name for the currently highlighted row."""
        table = self.query_one("#plugin-table", DataTable)
        cursor_row = table.cursor_row
        return self._row_plugin.get(cursor_row)

    # -- Actions --

    def action_toggle_row(self) -> None:
        """Toggle the currently highlighted row."""
        plugin_name = self._get_current_plugin()
        if plugin_name:
            self._toggle_plugin(plugin_name)

    def action_confirm(self) -> None:
        """Confirm selection and return to caller."""
        # Preserve category order from the plugins list
        result = [p.name for p in self._plugins if p.name in self._selected]
        self.dismiss(result)

    def action_select_all(self) -> None:
        """Select all plugins."""
        for plugin in self._plugins:
            self._selected.add(plugin.name)
            self._update_row_checkbox(plugin.name)
        self._update_status()

    def action_select_none(self) -> None:
        """Deselect all plugins."""
        for plugin in self._plugins:
            self._selected.discard(plugin.name)
            self._update_row_checkbox(plugin.name)
        self._update_status()

    def action_quit_screen(self) -> None:
        """Quit without selecting."""
        self.dismiss([])

    # -- Event handlers --

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Toggle selection when a row is clicked or Enter is pressed on it."""
        # DataTable.RowSelected fires on Enter/click. We use it to toggle.
        cursor_row = event.cursor_row
        plugin_name = self._row_plugin.get(cursor_row)
        if plugin_name:
            self._toggle_plugin(plugin_name)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle confirm/cancel button presses."""
        if event.button.id == "btn-confirm":
            self.action_confirm()
        elif event.button.id == "btn-cancel":
            self.action_quit_screen()
