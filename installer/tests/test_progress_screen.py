"""Regression tests for ProgressScreen's framework-logger contract.

Background: an earlier revision of ``installer/screens/progress.py`` defined
``def log(self, message: str)`` on the Screen subclass. Textual reserves
``log`` on ``MessagePump`` as a ``textual.Logger`` descriptor, and framework
code (e.g. ``Screen._reset_focus`` / ``Screen.set_focus``) calls
``self.log.debug(...)``. Overriding it as a user method caused an
``AttributeError: 'function' object has no attribute 'debug'`` during app
shutdown (``Screen._reset_focus`` → ``set_focus`` → ``self.log.debug``) when
any test pushed a ProgressScreen and the App was torn down.

These tests lock in the rename (``log`` → ``write_log``) so nobody
re-introduces the shadow.
"""

from __future__ import annotations

import pytest
from textual import Logger
from textual.app import App, ComposeResult
from textual.widgets import Static

from installer.screens.progress import ProgressScreen


class _Host(App):
    CSS = "Screen { align: center middle; }"

    def compose(self) -> ComposeResult:
        yield Static("")


def test_progress_screen_does_not_override_textual_log_attribute() -> None:
    """``ProgressScreen`` must not define its own ``log`` method.

    If this ever fails, someone re-added ``def log`` on ProgressScreen and
    shadowed Textual's ``DOMNode.log`` Logger descriptor — which crashes
    framework shutdown. Use ``write_log`` instead.
    """
    attr = ProgressScreen.__dict__.get("log")
    assert attr is None, (
        "ProgressScreen must not define its own `log` method — it shadows "
        "textual.DOMNode.log (a Logger descriptor) and crashes framework "
        "shutdown via `self.log.debug(...)`. Use `write_log` instead."
    )


def test_progress_screen_write_log_exists_and_is_callable() -> None:
    """The rename target must exist so the public API is preserved."""
    write_log = ProgressScreen.__dict__.get("write_log")
    assert write_log is not None, "ProgressScreen.write_log method missing"
    assert callable(write_log)


@pytest.mark.asyncio
async def test_progress_screen_log_attribute_is_textual_logger() -> None:
    """``instance.log`` must resolve to ``textual.Logger`` (not a bound method).

    Runs inside a live App so the Logger descriptor's ``active_app`` lookup
    works (it raises LookupError otherwise).
    """
    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = ProgressScreen(description="x", total=1)
        app.push_screen(screen)
        await pilot.pause()

        assert isinstance(screen.log, Logger)
        assert callable(screen.log.debug)


@pytest.mark.asyncio
async def test_progress_screen_shutdown_does_not_crash() -> None:
    """Direct regression for the original traceback.

    The original bug manifested as::

        AttributeError: 'function' object has no attribute 'debug'
        at textual/screen.py:1127 in set_focus: self.log.debug("focus was removed")

    ...during ``app._shutdown`` → ``_prune`` → ``_reset_focus`` → ``set_focus``.
    Push a ProgressScreen, trigger the same teardown path, and assert no
    exception escapes.
    """
    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = ProgressScreen(description="installing...", total=3)
        app.push_screen(screen)
        await pilot.pause()

        await screen.wait_ready()
        screen.write_log("step 1")
        screen.advance(1, detail="Step 1 done")
        await pilot.pause()
        # Falling out of the context manager triggers app._shutdown →
        # _prune → _reset_focus → set_focus → self.log.debug(...). If
        # ProgressScreen.log shadows the descriptor, this raises
        # AttributeError and fails the test.


@pytest.mark.asyncio
async def test_progress_screen_write_log_buffers_before_mount() -> None:
    """Behavior preservation: ``write_log`` before mount must buffer, not crash.

    This was the original reason for the method (messages logged before
    ``on_mount`` would otherwise hit the RichLog query before it existed).
    Keep the contract after the rename.
    """
    app = _Host()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = ProgressScreen(description="x", total=2)
        # Pre-mount: buffer should accept without raising.
        screen.write_log("pre-mount-line-1")
        screen.write_log("pre-mount-line-2")
        assert "pre-mount-line-1" in screen._log_buffer
        assert "pre-mount-line-2" in screen._log_buffer

        app.push_screen(screen)
        await pilot.pause()
        await screen.wait_ready()
        # After mount the buffer is flushed to the RichLog widget.
        assert screen._log_buffer == []
