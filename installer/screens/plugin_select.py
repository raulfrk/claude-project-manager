"""Plugin selection screen using Textual DataTable with category grouping."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DataTable, Footer, Static

from installer.plugin_status import PluginStatus
from installer.tui import (
    CATEGORY_ORDER,
    DEFAULT_PRESELECT,
    PluginInfo,
    load_plugins,
)

# Minimum width for the 3-column horizontal layout. Below this threshold
# PluginStatusScreen stacks the three state tables vertically.
THREE_COLUMN_MIN_WIDTH = 80

# Symbols for checkbox display
_CHECKED = "\u2611"  # ☑
_UNCHECKED = "\u2610"  # ☐


class PluginSelectScreen(Screen[list[str]]):
    """Interactive plugin selection with checkboxes grouped by category.

    Returns a list of selected plugin names via ``dismiss()``.

    Note: kept as a standalone widget for the CLI-mode selection path and
    unit/snapshot tests. Not used in the main TUI flow (app.py uses
    PluginStatusScreen instead, added in todo-535).
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
        color: $text;
        background: $accent;
        padding: 1 2;
    }

    #table-container {
        height: 1fr;
        margin: 1 2;
        border: round $primary-background;
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
        background: $warning 15%;
        border-top: solid $warning 50%;
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
        color: $accent;
        background: $surface;
        text-style: italic;
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
        branch: str | None = None,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._marketplace_path = marketplace_path
        self._branch = branch
        self._preselect = preselect if preselect is not None else DEFAULT_PRESELECT
        self._plugins: list[PluginInfo] = []
        # Map row index (0-based, skipping category rows) -> plugin name
        self._row_plugin: dict[int, str] = {}
        # Set of selected plugin names
        self._selected: set[str] = set()
        # Row keys for category separator rows (not selectable)
        self._category_rows: set[int] = set()

    def compose(self) -> ComposeResult:
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
        self._plugins = load_plugins(self._marketplace_path, branch=self._branch)
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
                styled_label = Text(f"  {cat_label}  ", style="bold reverse")
                table.add_row(
                    "",
                    styled_label,
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
        """Show warning if router is deselected but dependents are selected."""
        warning_bar = self.query_one("#warning-bar", Static)
        if "router" not in self._selected:
            dependents = [n for n in self._selected if n not in ("router", "analyse")]
            if dependents:
                warning_bar.update(
                    f"Warning: router not selected but recommended for: "
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


# ---------------------------------------------------------------------------
# PluginStatusScreen — three-column available/installed/outdated view
# ---------------------------------------------------------------------------

# Default action per plugin state. Cycling order differs by state — the
# "reinstall" option is only meaningful once a plugin is installed.
_DEFAULT_ACTION: dict[str, str] = {
    "available": "install",
    "installed": "skip",
    "outdated": "install",
}

_CYCLE_ORDER: dict[str, tuple[str, ...]] = {
    "available": ("install", "skip"),
    "installed": ("skip", "uninstall"),
    "outdated": ("install", "skip", "uninstall"),
}

_COLUMN_ORDER: tuple[str, ...] = ("available", "installed", "outdated")

_COLUMN_TITLE: dict[str, str] = {
    "available": "Available",
    "installed": "Installed",
    "outdated": "Outdated",
}


class PluginStatusScreen(Screen[list[tuple[str, str]]]):
    """Three-column plugin status screen with per-row action cycling.

    Shows plugins partitioned into available / installed / outdated DataTables
    and lets the user cycle through actions per row (install / reinstall /
    skip / uninstall) using Space. Enter confirms and dismisses with a list
    of ``(plugin_name, action)`` tuples for every row whose action is not
    ``"skip"``.

    The three-column layout renders horizontally when the screen is at least
    ``THREE_COLUMN_MIN_WIDTH`` cells wide and falls back to a vertical stack
    on narrower terminals. ``on_resize`` re-composes when the threshold is
    crossed.
    """

    CSS = """
    PluginStatusScreen {
        layout: vertical;
    }

    #title-bar {
        dock: top;
        height: 3;
        content-align: center middle;
        text-style: bold;
        color: $text;
        background: $accent;
        padding: 1 2;
    }

    #table-container {
        height: 1fr;
        margin: 1 2;
    }

    .status-column {
        border: round $primary-background;
        margin: 0 1;
        height: 1fr;
    }

    .status-title {
        text-style: bold;
        content-align: center middle;
        height: 1;
        color: $accent;
    }

    DataTable {
        height: 1fr;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        padding: 0 2;
        color: $accent;
        background: $surface;
        text-style: italic;
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
    """

    BINDINGS = [
        Binding("space", "cycle_action", "Cycle action", show=True),
        Binding("tab", "next_column", "Next column", show=True),
        Binding("enter", "confirm", "Confirm", show=True, priority=True),
        Binding("c", "confirm", "Confirm", show=False),
        Binding("q", "quit_screen", "Quit", show=True),
    ]

    def __init__(
        self,
        statuses: list[PluginStatus],
        *,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._statuses = statuses
        # name -> current action (install / reinstall / skip / uninstall)
        self._actions: dict[str, str] = {
            s.name: _DEFAULT_ACTION[s.state] for s in statuses
        }
        # Column layout state
        self._is_wide = True
        self._last_width = 0

    # -- Layout helpers --

    def _partitioned(self) -> dict[str, list[PluginStatus]]:
        """Group statuses by state."""
        buckets: dict[str, list[PluginStatus]] = {
            "available": [],
            "installed": [],
            "outdated": [],
        }
        for status in self._statuses:
            buckets[status.state].append(status)
        return buckets

    def _table_id(self, state: str) -> str:
        return f"status-table-{state}"

    # -- Compose / mount --

    def compose(self) -> ComposeResult:
        yield Static(
            "Plugin status — Space cycles action, Enter confirms", id="title-bar"
        )

        buckets = self._partitioned()
        # Width isn't known until after compose completes. We default to the
        # wide layout and re-compose in on_resize if the terminal is narrow.
        container_cls = Horizontal if self._is_wide else Vertical
        with container_cls(id="table-container"):
            for state in _COLUMN_ORDER:
                with Vertical(classes="status-column"):
                    yield Static(
                        f"{_COLUMN_TITLE[state]} ({len(buckets[state])})",
                        classes="status-title",
                    )
                    yield DataTable(
                        id=self._table_id(state),
                        cursor_type="row",
                        zebra_stripes=True,
                    )

        yield Static("", id="status-bar")
        with Horizontal(id="button-bar"):
            yield Button("Confirm", variant="primary", id="btn-confirm")
            yield Button("Cancel", variant="default", id="btn-cancel")
        yield Footer()

    def on_mount(self) -> None:
        self._populate_tables()
        self._update_status_bar()
        # Focus the first non-empty table so keyboard navigation works.
        first = self._first_focusable_table()
        if first is not None:
            first.focus()

    def _populate_tables(self) -> None:
        buckets = self._partitioned()
        for state in _COLUMN_ORDER:
            table = self.query_one(f"#{self._table_id(state)}", DataTable)
            table.clear(columns=True)
            table.add_columns("Plugin", "Installed", "Available", "Action")
            for status in buckets[state]:
                table.add_row(
                    status.name,
                    status.installed_version or "-",
                    status.available_version or "-",
                    self._actions[status.name],
                    key=f"row-{status.name}",
                )

    def _first_focusable_table(self) -> DataTable | None:
        buckets = self._partitioned()
        for state in _COLUMN_ORDER:
            if buckets[state]:
                return self.query_one(f"#{self._table_id(state)}", DataTable)
        return None

    def _update_status_bar(self) -> None:
        counts: dict[str, int] = {
            "install": 0,
            "reinstall": 0,
            "skip": 0,
            "uninstall": 0,
        }
        for action in self._actions.values():
            counts[action] += 1
        bar = self.query_one("#status-bar", Static)
        bar.update(
            f"install:{counts['install']} reinstall:{counts['reinstall']} "
            f"skip:{counts['skip']} uninstall:{counts['uninstall']}"
        )

    # -- Resize / layout swap --

    def on_resize(self, event) -> None:  # type: ignore[no-untyped-def]
        width = event.size.width if hasattr(event, "size") else event.width
        is_wide = width >= THREE_COLUMN_MIN_WIDTH
        # Ignore the first resize — compose() already used the correct
        # orientation and re-mounting during layout raises DuplicateIds.
        if self._last_width == 0:
            self._last_width = width
            self._is_wide = is_wide
            return
        if is_wide == self._is_wide:
            self._last_width = width
            return
        self._last_width = width
        self._is_wide = is_wide
        self.call_after_refresh(self._rebuild_container)

    def _rebuild_container(self) -> None:
        """Tear down and re-mount the table container after a layout swap."""
        try:
            container = self.query_one("#table-container")
        except Exception:
            return
        await_remove = container.remove()

        def _after_remove() -> None:
            buckets = self._partitioned()
            container_cls = Horizontal if self._is_wide else Vertical
            new_container = container_cls(id="table-container")
            self.mount(new_container, before="#status-bar")
            for state in _COLUMN_ORDER:
                column = Vertical(classes="status-column")
                new_container.mount(column)
                column.mount(
                    Static(
                        f"{_COLUMN_TITLE[state]} ({len(buckets[state])})",
                        classes="status-title",
                    )
                )
                table = DataTable(
                    id=self._table_id(state),
                    cursor_type="row",
                    zebra_stripes=True,
                )
                column.mount(table)
            self._populate_tables()

        # ``remove()`` returns an awaitable; schedule the rebuild for after it
        # completes so the old container is gone before we re-insert the id.
        self.app.call_later(self._await_and_rebuild, await_remove, _after_remove)

    async def _await_and_rebuild(self, awaitable, after) -> None:
        try:
            await awaitable
        except Exception:
            pass
        after()

    # -- Active table / row lookup --

    def _active_table(self) -> DataTable | None:
        focused = self.focused
        if isinstance(focused, DataTable):
            return focused
        return self._first_focusable_table()

    def _current_plugin_in(self, table: DataTable) -> PluginStatus | None:
        if table.row_count == 0:
            return None
        cursor_row = table.cursor_row
        if cursor_row < 0:
            return None
        # Find the state this table renders by matching its id.
        state = None
        for candidate in _COLUMN_ORDER:
            if table.id == self._table_id(candidate):
                state = candidate
                break
        if state is None:
            return None
        bucket = self._partitioned()[state]
        if cursor_row >= len(bucket):
            return None
        return bucket[cursor_row]

    def _update_action_cell(self, plugin_name: str, state: str) -> None:
        table = self.query_one(f"#{self._table_id(state)}", DataTable)
        row_key = f"row-{plugin_name}"
        col_key = table.ordered_columns[3].key
        table.update_cell(row_key, col_key, self._actions[plugin_name])

    # -- Actions --

    def action_cycle_action(self) -> None:
        table = self._active_table()
        if table is None:
            return
        plugin = self._current_plugin_in(table)
        if plugin is None:
            return
        cycle = _CYCLE_ORDER[plugin.state]
        current = self._actions[plugin.name]
        try:
            idx = cycle.index(current)
        except ValueError:
            idx = -1
        next_action = cycle[(idx + 1) % len(cycle)]
        self._actions[plugin.name] = next_action
        self._update_action_cell(plugin.name, plugin.state)
        self._update_status_bar()

    def action_next_column(self) -> None:
        buckets = self._partitioned()
        focused = self.focused
        current_state: str | None = None
        if isinstance(focused, DataTable):
            for candidate in _COLUMN_ORDER:
                if focused.id == self._table_id(candidate):
                    current_state = candidate
                    break
        order = list(_COLUMN_ORDER)
        if current_state is None:
            start = 0
        else:
            start = (order.index(current_state) + 1) % len(order)
        for offset in range(len(order)):
            state = order[(start + offset) % len(order)]
            if buckets[state]:
                table = self.query_one(f"#{self._table_id(state)}", DataTable)
                table.focus()
                return

    def action_confirm(self) -> None:
        result: list[tuple[str, str]] = []
        # Preserve marketplace order (self._statuses is already sorted).
        for status in self._statuses:
            action = self._actions[status.name]
            if action == "skip":
                continue
            result.append((status.name, action))
        self.dismiss(result)

    def action_quit_screen(self) -> None:
        self.dismiss([])

    # -- Event handlers --

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-confirm":
            self.action_confirm()
        elif event.button.id == "btn-cancel":
            self.action_quit_screen()
