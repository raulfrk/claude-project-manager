# installer/flow/update.py
"""prompt_toolkit-based replacement for Textual UpdateScreen.

Renders a checkbox list of outdated plugins with installed→available
versions. Returns the selected plugin names, or empty list on cancel.
"""

from __future__ import annotations

from prompt_toolkit.shortcuts import checkboxlist_dialog
from rich.console import Console


def select_updates(
    version_diffs: dict[str, tuple[str, str]], console: Console
) -> list[str]:
    """Prompt user to pick which plugins to update.

    Short-circuits with empty list when ``version_diffs`` is empty.
    """
    if not version_diffs:
        return []

    plugins = sorted(version_diffs.keys())
    values: list[tuple[str, str]] = []
    for name in plugins:
        installed, available = version_diffs[name]
        values.append((name, f"{name}  {installed} → {available}"))

    selected = checkboxlist_dialog(
        title="Plugin Updates Available",
        text="Select plugins to update (Space to toggle, Enter to confirm).",
        values=values,
        default_values=plugins,
    ).run()

    return selected or []
