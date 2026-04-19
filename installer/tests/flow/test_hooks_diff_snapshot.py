# installer/tests/flow/test_hooks_diff_snapshot.py
"""Syrupy snapshots for review_hooks_diff flow helper."""

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
            current_yaml="trigger: todo_complete\n",
            proposed_yaml="trigger: todo_complete\nblocking: true\n",
            unified_diff="--- todoist-auto\n+++ todoist-auto\n trigger: todo_complete\n+blocking: true\n",
        ),
    ]


def test_hooks_diff_snapshot(snapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot of hooks diff with new and changed entries."""
    monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "a")
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    review_hooks_diff(_diffs(), console)
    assert console.export_text() == snapshot


def test_hooks_diff_empty_snapshot(snapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot of hooks diff with no changes."""
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    result = review_hooks_diff([], console)
    assert result == {"apply": set(), "remove": set()}
    assert console.export_text() == snapshot
