"""TUI plugin selector using Rich."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich.text import Text

# Category display order and grouping
CATEGORY_ORDER: list[tuple[str, str]] = [
    ("core", "Core"),
    ("utilities", "Utilities"),
    ("integrations", "Integrations"),
]

# Map marketplace categories to installer categories.
# "productivity" (proj) is core; "utilities" is split by name.
_CORE_PLUGINS = {"sandbox", "hooks", "proj"}
_UTILITY_PLUGINS = {"worktree", "zoxide", "analyse"}
# Everything else falls into integrations.

# Plugins pre-selected by default (core set)
DEFAULT_PRESELECT = {"sandbox", "hooks", "proj"}

# Marketplace data path (relative to installer package)
_MARKETPLACE_PATH = (
    Path(__file__).resolve().parent.parent / ".claude-plugin" / "marketplace.json"
)


@dataclass
class PluginInfo:
    """Metadata for a single plugin."""

    name: str
    description: str
    version: str
    category: str
    keywords: list[str]


def _classify_category(plugin_name: str, marketplace_category: str) -> str:
    """Map a plugin to its installer category."""
    if plugin_name in _CORE_PLUGINS:
        return "core"
    if plugin_name in _UTILITY_PLUGINS:
        return "utilities"
    return "integrations"


def load_plugins(marketplace_path: Path | None = None) -> list[PluginInfo]:
    """Parse plugin metadata from the bundled marketplace.json.

    Args:
        marketplace_path: Override path to marketplace.json (for testing).

    Returns:
        List of PluginInfo sorted by category order then name.
    """
    path = marketplace_path or _MARKETPLACE_PATH
    data = json.loads(path.read_text(encoding="utf-8"))

    plugins: list[PluginInfo] = []
    for entry in data.get("plugins", []):
        category = _classify_category(entry["name"], entry.get("category", ""))
        plugins.append(
            PluginInfo(
                name=entry["name"],
                description=entry.get("description", ""),
                version=entry.get("version", "0.0.0"),
                category=category,
                keywords=entry.get("keywords", []),
            )
        )

    # Sort by category order, then alphabetically by name within category
    cat_index = {cat: i for i, (cat, _) in enumerate(CATEGORY_ORDER)}
    plugins.sort(key=lambda p: (cat_index.get(p.category, 99), p.name))
    return plugins


def _build_selection_table(
    plugins: list[PluginInfo], preselected: set[str]
) -> tuple[Table, dict[int, PluginInfo]]:
    """Build a Rich table with numbered plugin rows grouped by category.

    Returns the table and a 1-based index map.
    """
    table = Table(title="Available Plugins", show_lines=False, pad_edge=True)
    table.add_column("#", style="bold cyan", justify="right", width=3)
    table.add_column("Plugin", style="bold")
    table.add_column("Version", style="dim")
    table.add_column("Description")
    table.add_column("Default", justify="center")

    index_map: dict[int, PluginInfo] = {}
    idx = 1
    current_category = ""

    for plugin in plugins:
        if plugin.category != current_category:
            current_category = plugin.category
            cat_label = next(
                (label for cat, label in CATEGORY_ORDER if cat == current_category),
                current_category.title(),
            )
            table.add_section()
            table.add_row("", Text(f"[{cat_label}]", style="bold magenta"), "", "", "")

        default_mark = "*" if plugin.name in preselected else ""
        table.add_row(
            str(idx), plugin.name, plugin.version, plugin.description, default_mark
        )
        index_map[idx] = plugin
        idx += 1

    return table, index_map


def _check_dependency_warnings(selected_names: list[str], console: Console) -> None:
    """Warn if hooks is deselected but other core plugins are selected."""
    if "hooks" not in selected_names:
        hook_dependents = [n for n in selected_names if n not in ("hooks", "analyse")]
        if hook_dependents:
            console.print(
                f"\n[yellow]Warning:[/yellow] [bold]hooks[/bold] is not selected but "
                f"is recommended for: {', '.join(hook_dependents)}. "
                f"Hook dispatch will be disabled for these plugins."
            )


def select_plugins(
    plugins: list[PluginInfo],
    preselect: set[str] | None = None,
    console: Console | None = None,
) -> list[str]:
    """Interactive plugin selection using Rich numbered-list display.

    Displays plugins grouped by category with a numbered list.
    Accepts comma-separated indices, "all", or "none".
    Default pre-selects core plugins.

    Args:
        plugins: Available plugins to choose from.
        preselect: Plugin names to pre-select. Defaults to core plugins.
        console: Rich console instance (created if not provided).

    Returns:
        List of selected plugin names.
    """
    if console is None:
        console = Console()

    preselected = preselect if preselect is not None else DEFAULT_PRESELECT

    table, index_map = _build_selection_table(plugins, preselected)
    console.print()
    console.print(table)

    default_indices = [
        str(idx) for idx, p in index_map.items() if p.name in preselected
    ]
    default_str = ",".join(default_indices)

    console.print(
        "\nEnter plugin numbers (comma-separated),"
        " [bold]all[/bold], or [bold]none[/bold]."
    )
    console.print(f"[dim]Default (core): {default_str}[/dim]")

    response = Prompt.ask("Plugins to install", default=default_str).strip()

    if response.lower() == "all":
        selected = [p.name for p in plugins]
    elif response.lower() == "none":
        selected = []
    else:
        indices: list[int] = []
        for part in response.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part)
                if idx in index_map:
                    indices.append(idx)
                else:
                    console.print(f"[yellow]Skipping invalid index: {idx}[/yellow]")
            elif part:
                console.print(f"[yellow]Skipping invalid input: {part}[/yellow]")

        selected = [index_map[i].name for i in sorted(set(indices))]

    _check_dependency_warnings(selected, console)

    if selected:
        console.print(f"\n[green]Selected:[/green] {', '.join(selected)}")
    else:
        console.print("\n[dim]No plugins selected.[/dim]")

    return selected
