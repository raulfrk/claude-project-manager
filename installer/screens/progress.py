"""Progress screen for long-running operations."""

from __future__ import annotations

import asyncio

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, ProgressBar, RichLog, Static


class ProgressScreen(Screen[None]):
    """Display a progress bar and scrolling log during long operations.

    Accepts a description and total steps. Call ``advance()`` to
    increment progress and ``log()`` to append log lines.
    Auto-dismisses when progress reaches total.

    All public methods are safe to call before the screen is mounted —
    calls are buffered and replayed on mount.

    Args:
        description: Text displayed above the progress bar.
        total: Total number of steps for the progress bar.
    """

    AUTO_FOCUS = ""

    CSS = """
    ProgressScreen {
        layout: vertical;
        align: center middle;
    }

    #progress-container {
        width: 80;
        height: auto;
        max-height: 85%;
        padding: 2 4;
        border: round $accent;
        background: $surface;
    }

    ProgressScreen.--complete #progress-container {
        border: round $success;
    }

    #progress-description {
        text-style: bold;
        color: $text;
        background: $accent;
        content-align: center middle;
        height: 3;
        padding: 0 2;
        margin: 0 0 1 0;
    }

    ProgressScreen.--complete #progress-description {
        background: $success;
    }

    #progress-detail {
        height: auto;
        padding: 0 2 1 2;
        color: $text-muted;
        content-align: center middle;
        text-style: italic;
    }

    ProgressBar {
        margin: 1 2;
    }

    #progress-status {
        height: 1;
        padding: 0 2;
        color: $accent;
        content-align: center middle;
    }

    #progress-log {
        height: 12;
        margin: 1 2 0 2;
        border: round $primary-background;
        background: $surface-darken-1;
        scrollbar-size: 1 1;
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
        self._mounted = asyncio.Event()
        self._log_buffer: list[str] = []
        self._advance_buffer: list[tuple[int, str]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="progress-container"):
            yield Static(self._description, id="progress-description")
            yield Static("", id="progress-detail")
            yield ProgressBar(total=self._total, id="progress-bar")
            yield Static("", id="progress-status")
            yield RichLog(id="progress-log", wrap=True, markup=True)
        yield Footer()

    def on_mount(self) -> None:
        self._update_status()
        # Replay any buffered calls
        log_widget = self.query_one("#progress-log", RichLog)
        for msg in self._log_buffer:
            log_widget.write(msg)
        self._log_buffer.clear()
        for steps, detail in self._advance_buffer:
            self._do_advance(steps, detail)
        self._advance_buffer.clear()
        self._mounted.set()

    async def wait_ready(self) -> None:
        """Wait until the screen is fully mounted."""
        await self._mounted.wait()

    def _update_status(self) -> None:
        """Update the status text with current/total count."""
        status = self.query_one("#progress-status", Static)
        status.update(f"{self._current}/{self._total}")

    def write_log(self, message: str) -> None:
        """Append a line to the log area. Safe to call before mount.

        Named ``write_log`` (not ``log``) because Textual's ``DOMNode.log``
        is a reserved Logger descriptor; overriding it as a method breaks
        framework internals like ``self.log.debug(...)`` during shutdown.
        """
        if not self._mounted.is_set():
            self._log_buffer.append(message)
            return
        log_widget = self.query_one("#progress-log", RichLog)
        log_widget.write(message)

    def advance(self, steps: int = 1, detail: str = "") -> None:
        """Increment the progress bar. Safe to call before mount."""
        if not self._mounted.is_set():
            self._advance_buffer.append((steps, detail))
            return
        self._do_advance(steps, detail)

    def _do_advance(self, steps: int, detail: str) -> None:
        """Actual advance logic (only called when mounted)."""
        self._current = min(self._current + steps, self._total)
        bar = self.query_one("#progress-bar", ProgressBar)
        bar.advance(steps)

        if detail:
            detail_widget = self.query_one("#progress-detail", Static)
            detail_widget.update(detail)

        self._update_status()

        if self._current >= self._total:
            self.add_class("--complete")
            self.dismiss(None)
