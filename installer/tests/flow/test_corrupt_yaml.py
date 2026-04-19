# installer/tests/flow/test_corrupt_yaml.py
import pytest
import yaml
from rich.console import Console

from installer.flow.corrupt_yaml import show_corrupt_yaml_and_confirm


def _errors() -> dict[str, Exception]:
    try:
        yaml.safe_load("{invalid: [")
    except yaml.YAMLError as e:
        return {"proj": e, "worktree": yaml.YAMLError("bad token")}
    return {}


class TestShowCorruptYamlAndConfirm:
    def test_continue(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "y")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert show_corrupt_yaml_and_confirm(_errors(), console) is True

    def test_cancel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert show_corrupt_yaml_and_confirm(_errors(), console) is False

    def test_renders_bucket_and_reason(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "n")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        show_corrupt_yaml_and_confirm(_errors(), console)
        text = console.export_text()
        assert "proj" in text
        assert "worktree" in text
        assert "bad token" in text or "YAMLError" in text
        assert ".claude" in text

    def test_empty_errors_returns_true_without_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        prompt_called = {"n": 0}

        def fake_ask(*a, **k):
            prompt_called["n"] += 1
            return "y"

        monkeypatch.setattr("rich.prompt.Prompt.ask", fake_ask)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert show_corrupt_yaml_and_confirm({}, console) is True
        assert prompt_called["n"] == 0
