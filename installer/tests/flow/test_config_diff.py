# installer/tests/flow/test_config_diff.py
import pytest
from rich.console import Console

from installer.flow.config_diff import review_config_diff


_DIFF = """\
--- a/todoist.yaml
+++ b/todoist.yaml
@@ -1 +1 @@
-api_token: old
+api_token: new
"""


class TestReviewConfigDiff:
    def test_apply(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("installer.flow.config_diff.ask_yn", lambda *a, **k: True)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert review_config_diff("Todoist", _DIFF, console) is True

    def test_cancel(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("installer.flow.config_diff.ask_yn", lambda *a, **k: False)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert review_config_diff("Todoist", _DIFF, console) is False

    def test_renders_service_and_diff(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("installer.flow.config_diff.ask_yn", lambda *a, **k: False)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        review_config_diff("Todoist", _DIFF, console)
        text = console.export_text()
        assert "Todoist" in text
        assert "api_token" in text

    def test_empty_diff_returns_true_without_prompt(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        count = {"n": 0}

        def fake_ask(*a, **k):
            count["n"] += 1
            return True

        monkeypatch.setattr("installer.flow.config_diff.ask_yn", fake_ask)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert review_config_diff("Todoist", "", console) is True
        assert count["n"] == 0
