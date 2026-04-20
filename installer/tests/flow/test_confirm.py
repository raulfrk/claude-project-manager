import pytest
from rich.console import Console

from installer.flow.confirm import ConfirmOption, ConfirmResult, confirm_with_options


class TestConfirmWithOptions:
    def test_confirmed_no_options(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("installer.flow.confirm.ask_yn", lambda *a, **k: True)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = confirm_with_options(
            title="Proceed?", message="Do the thing?", options=[], console=console
        )
        assert isinstance(result, ConfirmResult)
        assert result.confirmed is True
        assert result.options == {}

    def test_cancelled_no_options(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("installer.flow.confirm.ask_yn", lambda *a, **k: False)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = confirm_with_options(
            title="Proceed?", message="Do the thing?", options=[], console=console
        )
        assert result.confirmed is False
        assert result.options == {}

    def test_confirmed_with_option_accepted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = iter([True, True])
        monkeypatch.setattr(
            "installer.flow.confirm.ask_yn", lambda *a, **k: next(calls)
        )
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = confirm_with_options(
            title="Reinstall?",
            message="Reinstall all plugins.",
            options=[ConfirmOption(key="reset_configs", label="Reset configs")],
            console=console,
        )
        assert result.confirmed is True
        assert result.options == {"reset_configs": True}

    def test_confirmed_with_option_declined(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = iter([True, False])
        monkeypatch.setattr(
            "installer.flow.confirm.ask_yn", lambda *a, **k: next(calls)
        )
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = confirm_with_options(
            title="Reinstall?",
            message="Reinstall all plugins.",
            options=[ConfirmOption(key="reset_configs", label="Reset configs")],
            console=console,
        )
        assert result.confirmed is True
        assert result.options == {"reset_configs": False}

    def test_cancel_skips_option_prompts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        call_count = {"n": 0}

        def fake_ask(*args, **kwargs):
            call_count["n"] += 1
            return False

        monkeypatch.setattr("installer.flow.confirm.ask_yn", fake_ask)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = confirm_with_options(
            title="Reinstall?",
            message="Reinstall all plugins.",
            options=[ConfirmOption(key="reset_configs", label="Reset configs")],
            console=console,
        )
        assert result.confirmed is False
        assert call_count["n"] == 1

    def test_message_rendered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("installer.flow.confirm.ask_yn", lambda *a, **k: False)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        confirm_with_options(
            title="My Title",
            message="My specific message",
            options=[],
            console=console,
        )
        text = console.export_text()
        assert "My Title" in text
        assert "My specific message" in text

    def test_variant_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("installer.flow.confirm.ask_yn", lambda *a, **k: True)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = confirm_with_options(
            title="Uninstall?",
            message="Remove all?",
            options=[],
            console=console,
            variant="error",
        )
        assert result.confirmed is True
