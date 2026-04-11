"""Tests for CorruptYamlScreen modal."""

from __future__ import annotations

from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from installer._config_loader import ConfigLoadError
from installer.screens.corrupt_yaml import CorruptYamlScreen


class _TestApp(App):
    def compose(self) -> ComposeResult:
        yield Static("root")


@pytest.mark.asyncio
async def test_continue_dismisses_true() -> None:
    errors = {
        "proj": ConfigLoadError(Path("/fake/proj.yaml"), ValueError("bad yaml")),
    }
    app = _TestApp()
    results: list[bool | None] = []
    async with app.run_test(size=(120, 40)) as pilot:
        screen = CorruptYamlScreen(errors)
        app.push_screen(screen, callback=lambda r: results.append(r))
        await pilot.pause()
        # Buttons in a modal may have z-order / focus edge cases under pilot.
        # Trigger the handler directly via on_button_pressed for a reliable unit.
        from textual.widgets import Button

        btn = screen.query_one("#btn-continue", Button)
        screen.on_button_pressed(Button.Pressed(btn))
        await pilot.pause()
    assert results == [True]


@pytest.mark.asyncio
async def test_cancel_dismisses_false() -> None:
    errors = {
        "proj": ConfigLoadError(Path("/fake/proj.yaml"), ValueError("bad yaml")),
    }
    app = _TestApp()
    results: list[bool | None] = []
    async with app.run_test(size=(120, 40)) as pilot:
        screen = CorruptYamlScreen(errors)
        app.push_screen(screen, callback=lambda r: results.append(r))
        await pilot.pause()
        from textual.widgets import Button

        btn = screen.query_one("#btn-cancel", Button)
        screen.on_button_pressed(Button.Pressed(btn))
        await pilot.pause()
    assert results == [False]


@pytest.mark.asyncio
async def test_escape_dismisses_false() -> None:
    errors = {
        "worktree": ConfigLoadError(
            Path("/fake/worktree.yaml"), ValueError("tab character")
        ),
    }
    app = _TestApp()
    results: list[bool | None] = []
    async with app.run_test(size=(120, 40)) as pilot:
        screen = CorruptYamlScreen(errors)
        app.push_screen(screen, callback=lambda r: results.append(r))
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
    assert results == [False]


@pytest.mark.asyncio
async def test_multiple_errors_displayed() -> None:
    errors = {
        "proj": ConfigLoadError(Path("/a/proj.yaml"), ValueError("parse error 1")),
        "worktree": ConfigLoadError(
            Path("/a/worktree.yaml"), ValueError("parse error 2")
        ),
    }
    app = _TestApp()
    async with app.run_test(size=(120, 40)) as pilot:
        screen = CorruptYamlScreen(errors)
        app.push_screen(screen)
        await pilot.pause()
        # Both bucket names should appear in the rendered content.
        # Textual's Static stores text in the name-mangled _Static__content.
        static_texts = []
        for s in screen.query(Static):
            content = getattr(s, "_Static__content", None)
            if content is not None:
                static_texts.append(str(content))
        joined = " ".join(static_texts)
        assert "proj.yaml" in joined
        assert "worktree.yaml" in joined
        assert "parse error 1" in joined
        assert "parse error 2" in joined
