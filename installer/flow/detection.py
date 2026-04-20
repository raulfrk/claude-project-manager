"""Rich-based replacement for Textual DetectionScreen.

Renders a detection summary table (plugin name, installed + available
versions, derived status) then prompts y/n to continue.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from rich.console import Console
from rich.table import Table

from installer.flow.yn import ask_yn

if TYPE_CHECKING:
    from installer.detect import InstallState


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


_STATUS_STYLE: dict[str, str] = {
    "up-to-date": "green",
    "outdated": "yellow",
    "not installed": "dim",
    "unknown": "dim",
}


def show_detection_and_confirm(
    state: "InstallState",
    rows: list["PluginDetectionRow"],
    title: str,
    console: Console,
) -> bool:
    """Render the detection table + prompt for proceed/cancel.

    Returns ``True`` if user opts to continue, ``False`` on cancel.
    """
    console.print(f"[bold]{title}[/bold]")

    table = Table(show_header=True, header_style="bold")
    table.add_column("Plugin")
    table.add_column("Installed")
    table.add_column("Available")
    table.add_column("Status")
    for row in rows:
        status = row.status
        style = _STATUS_STYLE.get(status, "")
        status_text = f"[{style}]{status}[/{style}]" if style else status
        table.add_row(
            row.plugin,
            row.installed_version or "—",
            row.available_version or "—",
            status_text,
        )
    console.print(table)

    return ask_yn("Continue?", default=True, console=console)
