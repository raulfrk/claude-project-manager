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


class TestStderrWarnings:
    def test_int_in_range_out_of_range_warning(
        self,
        console: Console,
        capfd: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("COLUMNS", "200")
        # First attempt out-of-range, second returns a valid value.
        with patch("installer.prompts.IntPrompt.ask", side_effect=[100, 7]):
            assert int_in_range("prompt", 5, 1, 10, console) == 7
        err = capfd.readouterr().err
        assert "Value must be between 1 and 10" in err

    def test_int_in_range_three_failures_fallback(
        self,
        console: Console,
        capfd: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("COLUMNS", "200")
        with patch("installer.prompts.IntPrompt.ask", side_effect=[100, 200, 300]):
            assert int_in_range("prompt", 5, 1, 10, console) == 5
        err = capfd.readouterr().err
        # Expect 3 per-attempt warnings + 1 final fallback warning.
        assert err.count("Value must be between 1 and 10") == 3
        assert "3 invalid attempts" in err
        assert "falling back to default 5" in err

    def test_prompt_choice_invalid_warning(
        self,
        console: Console,
        capfd: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("COLUMNS", "200")
        with patch("installer.prompts.Prompt.ask", return_value="fast"):
            result = prompt_choice(
                "prompt", "blazing", ["fast", "balanced", "careful"], console
            )
        assert result in ["fast", "balanced", "careful"]
        err = capfd.readouterr().err
        assert "not one of" in err
        assert "coercing to 'fast'" in err

    def test_int_in_range_lang_c_non_ascii(
        self,
        console: Console,
        capfd: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pin LANG=C; ensure non-ASCII default display does not crash.
        monkeypatch.setenv("LANG", "C")
        monkeypatch.setenv("LC_ALL", "C")
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("COLUMNS", "200")
        # IntPrompt.ask returns an int out of range to force the stderr path.
        # The non-ASCII content is embedded in the prompt string itself — the
        # stderr Console must encode it without UnicodeEncodeError.
        with patch("installer.prompts.IntPrompt.ask", side_effect=[100, 5]):
            assert int_in_range("prompt★", 5, 1, 10, console) == 5
        # Should reach this line without a UnicodeEncodeError crash.
        _ = capfd.readouterr().err

    def test_int_in_range_wrap_width_200(
        self,
        console: Console,
        capfd: pytest.CaptureFixture[str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pin COLUMNS=200 to avoid Rich soft-wrap breaking substring matches.
        monkeypatch.setenv("NO_COLOR", "1")
        monkeypatch.setenv("COLUMNS", "200")
        with patch("installer.prompts.IntPrompt.ask", side_effect=[100, 5]):
            assert int_in_range("prompt", 5, 1, 10, console) == 5
        err = capfd.readouterr().err
        # The full substring must appear on a single logical line (no wrap).
        assert "Value must be between 1 and 10" in err
