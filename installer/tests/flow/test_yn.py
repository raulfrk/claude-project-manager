"""Tests for installer.flow.yn: ask_yn + install_confirm_patch."""

from __future__ import annotations

import builtins
from unittest.mock import patch

import pytest
from rich.console import Console
from rich.prompt import Confirm, InvalidResponse

from installer.flow.yn import _YesNoPrompt, ask_yn, install_confirm_patch


@pytest.fixture(autouse=True)
def _patch() -> None:
    """Confirm.process_response persists across tests — apply patch once."""
    install_confirm_patch()


class TestAskYn:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("y", True),
            ("Y", True),
            ("yes", True),
            ("YES", True),
            ("Yes", True),
            ("  yes  ", True),
            ("n", False),
            ("N", False),
            ("no", False),
            ("NO", False),
        ],
    )
    def test_accepts_yes_no_forms(self, raw: str, expected: bool) -> None:
        with patch.object(builtins, "input", return_value=raw):
            assert ask_yn("proceed?", default=False, console=Console()) is expected

    def test_invalid_then_default(self) -> None:
        # 1st call returns "maybe" (rejected), 2nd returns "" (accept default).
        inputs = iter(["maybe", ""])
        with patch.object(builtins, "input", side_effect=lambda *a: next(inputs)):
            assert ask_yn("proceed?", default=True, console=Console()) is True

    def test_empty_returns_default_true(self) -> None:
        with patch.object(builtins, "input", return_value=""):
            assert ask_yn("proceed?", default=True, console=Console()) is True

    def test_empty_returns_default_false(self) -> None:
        with patch.object(builtins, "input", return_value=""):
            assert ask_yn("proceed?", default=False, console=Console()) is False

    def test_process_response_rejects_unknown(self) -> None:
        prompt = _YesNoPrompt("t", console=Console())
        with pytest.raises(InvalidResponse):
            prompt.process_response("maybe")


class TestConfirmPatch:
    def test_widened_confirm_accepts_yes(self) -> None:
        with patch.object(builtins, "input", return_value="yes"):
            assert Confirm.ask("continue?", default=False) is True

    def test_widened_confirm_accepts_no(self) -> None:
        with patch.object(builtins, "input", return_value="no"):
            assert Confirm.ask("continue?", default=True) is False

    def test_widened_confirm_case_insensitive(self) -> None:
        with patch.object(builtins, "input", return_value="YES"):
            assert Confirm.ask("continue?", default=False) is True

    def test_widened_confirm_still_rejects_garbage(self) -> None:
        # Invalid input → re-prompt. Second call returns "" → accept default.
        inputs = iter(["asdf", ""])
        with patch.object(builtins, "input", side_effect=lambda *a: next(inputs)):
            assert Confirm.ask("continue?", default=True) is True

    def test_patch_is_idempotent(self) -> None:
        # Calling twice must not corrupt Confirm.
        install_confirm_patch()
        install_confirm_patch()
        with patch.object(builtins, "input", return_value="y"):
            assert Confirm.ask("x", default=False) is True
