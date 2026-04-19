# installer/tests/flow/test_hooks_diff.py
import pytest
from rich.console import Console

from installer.flow.hooks_diff import review_hooks_diff
from installer.hooks_diff import HookDiff


def _diffs() -> list[HookDiff]:
    return [
        HookDiff(
            hook_id="proj-tracking-flush",
            status="new",
            current_yaml=None,
            proposed_yaml="trigger: todo_add\ntarget: tracking_git_flush\n",
            unified_diff="--- /dev/null\n+++ proj-tracking-flush\n+trigger: todo_add\n",
        ),
        HookDiff(
            hook_id="todoist-auto",
            status="changed",
            current_yaml="trigger: todo_add\n",
            proposed_yaml="trigger: todo_add_batch\n",
            unified_diff="--- todoist-auto\n+++ todoist-auto\n-trigger: todo_add\n+trigger: todo_add_batch\n",
        ),
        HookDiff(
            hook_id="stale-hook",
            status="removed",
            current_yaml="trigger: x\n",
            proposed_yaml=None,
            unified_diff="--- stale-hook\n+++ /dev/null\n-trigger: x\n",
        ),
    ]


class TestReviewHooksDiff:
    def test_empty_returns_empty_dict(self) -> None:
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = review_hooks_diff([], console)
        assert result == {"apply": set(), "remove": set()}

    def test_apply_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "a")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = review_hooks_diff(_diffs(), console)
        assert result == {
            "apply": {"proj-tracking-flush", "todoist-auto"},
            "remove": {"stale-hook"},
        }

    def test_skip_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "s")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = review_hooks_diff(_diffs(), console)
        assert result == {"apply": set(), "remove": set()}

    def test_cancel_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "c")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert review_hooks_diff(_diffs(), console) is None

    def test_diff_content_rendered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "c")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        review_hooks_diff(_diffs(), console)
        text = console.export_text()
        assert "proj-tracking-flush" in text
        assert "todoist-auto" in text
        assert "stale-hook" in text
