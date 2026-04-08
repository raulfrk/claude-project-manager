"""Progress screen for long-running operations."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, ProgressBar, Static


class ProgressScreen(Screen[None]):
    """Display a progress bar during long operations.

    Accepts a description and total steps. Call ``advance()`` to
    increment progress. Auto-dismisses when progress reaches total.

    Args:
        description: Text displayed above the progress bar.
        total: Total number of steps for the progress bar.
    """

    CSS = """
    ProgressScreen {
        layout: vertical;
        align: center middle;
    }

    #progress-container {
        width: 70;
        height: auto;
        padding: 2 4;
        border: tall $accent;
        background: $surface;
    }

    #progress-description {
        text-style: bold;
        color: $accent;
        content-align: center middle;
        height: 3;
        padding: 0 2;
    }

    #progress-detail {
        height: auto;
        padding: 0 2 1 2;
        color: $text-muted;
        content-align: center middle;
    }

    ProgressBar {
        margin: 1 2;
    }

    #progress-status {
        height: 1;
        padding: 0 2;
        color: $text-muted;
        content-align: center middle;
    }
    """

    def __init__(
        self,
        description: str,
        total: int,
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self._description = description
        self._total = total
        self._current = 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="progress-container"):
            yield Static(self._description, id="progress-description")
            yield Static("", id="progress-detail")
            yield ProgressBar(total=self._total, id="progress-bar")
            yield Static("", id="progress-status")
        yield Footer()

    def on_mount(self) -> None:
        self._update_status()

    def _update_status(self) -> None:
        """Update the status text with current/total count."""
        status = self.query_one("#progress-status", Static)
        status.update(f"{self._current}/{self._total}")

    def advance(self, steps: int = 1, detail: str = "") -> None:
        """Increment the progress bar.

        Args:
            steps: Number of steps to advance (default 1).
            detail: Optional detail text shown below the description.
        """
        self._current = min(self._current + steps, self._total)
        bar = self.query_one("#progress-bar", ProgressBar)
        bar.advance(steps)

        if detail:
            detail_widget = self.query_one("#progress-detail", Static)
            detail_widget.update(detail)

        self._update_status()

        if self._current >= self._total:
            self.dismiss(None)
