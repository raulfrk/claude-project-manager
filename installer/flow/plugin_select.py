# installer/flow/plugin_select.py
"""prompt_toolkit-based replacement for Textual PluginStatusScreen.

Three sequential checkboxlist dialogs — one per status bucket:
  1. Available (state="available"): selection → action="install"
  2. Outdated (state="outdated"): selection → action="install" (update == install-latest)
  3. Installed (state="installed"): selection → action="reinstall"

Returns a list of (plugin_name, action) tuples for every selected plugin.
Cancel at any dialog short-circuits to [].
"""

from __future__ import annotations

from prompt_toolkit.shortcuts import checkboxlist_dialog
from rich.console import Console

from installer.plugin_status import PluginStatus


def _prompt_bucket(
    title: str, text: str, values: list[tuple[str, str]]
) -> list[str] | None:
    """Fire a checkboxlist dialog. Return None if the bucket is empty (skip)."""
    if not values:
        return None
    return checkboxlist_dialog(title=title, text=text, values=values).run()


def select_plugin_actions(
    statuses: list[PluginStatus], console: Console
) -> list[tuple[str, str]]:
    """Prompt per-bucket selections, return flat list of (name, action).

    Cancel (dialog returns None explicitly) → return [] early.
    Empty ``statuses`` or empty bucket → skip that dialog silently.
    """
    if not statuses:
        return []

    available = [s for s in statuses if s.state == "available"]
    outdated = [s for s in statuses if s.state == "outdated"]
    installed = [s for s in statuses if s.state == "installed"]

    actions: list[tuple[str, str]] = []

    # 1. Available → install
    picks = _prompt_bucket(
        "Available Plugins",
        "Select plugins to install:",
        [(s.name, f"{s.name}  (available {s.available_version})") for s in available],
    )
    if picks is None and available:
        # User cancelled (None response on a non-empty dialog).
        return []
    if picks:
        for name in picks:
            actions.append((name, "install"))

    # 2. Outdated → install (update == install-latest)
    picks = _prompt_bucket(
        "Outdated Plugins",
        "Select plugins to update:",
        [
            (s.name, f"{s.name}  {s.installed_version} → {s.available_version}")
            for s in outdated
        ],
    )
    if picks is None and outdated:
        return []
    if picks:
        for name in picks:
            actions.append((name, "install"))

    # 3. Installed → reinstall
    picks = _prompt_bucket(
        "Installed Plugins",
        "Select plugins to reinstall (leave blank to skip):",
        [(s.name, f"{s.name}  {s.installed_version}") for s in installed],
    )
    if picks is None and installed:
        return []
    if picks:
        for name in picks:
            actions.append((name, "reinstall"))

    return actions
