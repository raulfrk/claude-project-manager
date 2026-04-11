"""Tests for installer/prompts.py — Rich helper functions."""

from __future__ import annotations

from io import StringIO
from unittest.mock import patch

import pytest
from rich.console import Console

from installer.prompts import int_in_range, prompt_choice


@pytest.fixture
def console() -> Console:
    return Console(file=StringIO(), force_terminal=False, width=80)


class TestIntInRange:
    def test_valid_input_returned(self, console: Console) -> None:
        with patch("installer.prompts.IntPrompt.ask", return_value=5):
            assert int_in_range("prompt", 3, 1, 10, console) == 5

    def test_default_on_eof(self, console: Console) -> None:
        with patch("installer.prompts.IntPrompt.ask", side_effect=EOFError):
            assert int_in_range("prompt", 3, 1, 10, console) == 3

    def test_out_of_range_falls_through_to_default(
        self,
        console: Console,
        capfd: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # 3 consecutive out-of-range returns should fall through.
        # capfd captures _err's real stderr FD output; NO_COLOR strips ANSI;
        # COLUMNS=200 prevents Rich soft-wrap from breaking substring matches.
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("COLUMNS", "200")
        with patch("installer.prompts.IntPrompt.ask", return_value=100):
            assert int_in_range("prompt", 5, 1, 10, console) == 5
        err = capfd.readouterr().err
        assert "Value must be between" in err
        assert "falling back to default" in err

    def test_default_clamped_into_range(self, console: Console) -> None:
        with patch("installer.prompts.IntPrompt.ask", side_effect=EOFError):
            # default=50 out of [1,10], should clamp to 10
            assert int_in_range("prompt", 50, 1, 10, console) == 10


class TestPromptChoice:
    def test_valid_choice_returned(self, console: Console) -> None:
        with patch("installer.prompts.Prompt.ask", return_value="careful"):
            assert (
                prompt_choice("prompt", "careful", ["fast", "careful"], console)
                == "careful"
            )

    def test_invalid_default_coerced_to_first(
        self,
        console: Console,
        capfd: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # default="blazing" not in choices → coerced to "fast".
        # capfd captures _err's real stderr FD output.
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("COLUMNS", "200")
        with patch("installer.prompts.Prompt.ask", side_effect=EOFError):
            assert (
                prompt_choice("prompt", "blazing", ["fast", "careful"], console)
                == "fast"
            )
        err = capfd.readouterr().err
        assert "not one of" in err
        assert "coercing to 'fast'" in err

    def test_default_on_eof(self, console: Console) -> None:
        with patch("installer.prompts.Prompt.ask", side_effect=EOFError):
            assert (
                prompt_choice("prompt", "fast", ["fast", "careful"], console) == "fast"
            )
