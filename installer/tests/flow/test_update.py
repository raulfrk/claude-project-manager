# installer/tests/flow/test_update.py
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from installer.flow.update import select_updates


_DIFFS = {
    "proj": ("1.0.0", "1.1.0"),
    "worktree": ("2.0.0", "2.0.1"),
    "router": ("3.0.0", "3.1.0"),
}


class TestSelectUpdates:
    def test_all_selected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_dialog = MagicMock()
        mock_dialog.return_value.run.return_value = ["proj", "worktree", "router"]
        monkeypatch.setattr("installer.flow.update.checkboxlist_dialog", mock_dialog)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = select_updates(_DIFFS, console)
        assert sorted(result) == ["proj", "router", "worktree"]
        call_kwargs = mock_dialog.call_args.kwargs
        assert set(call_kwargs.get("default_values", [])) == {
            "proj",
            "worktree",
            "router",
        }

    def test_partial_selection(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_dialog = MagicMock()
        mock_dialog.return_value.run.return_value = ["proj"]
        monkeypatch.setattr("installer.flow.update.checkboxlist_dialog", mock_dialog)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = select_updates(_DIFFS, console)
        assert result == ["proj"]

    def test_cancel_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_dialog = MagicMock()
        mock_dialog.return_value.run.return_value = None
        monkeypatch.setattr("installer.flow.update.checkboxlist_dialog", mock_dialog)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert select_updates(_DIFFS, console) == []

    def test_empty_diffs_returns_empty_without_dialog(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        mock_dialog = MagicMock()
        monkeypatch.setattr("installer.flow.update.checkboxlist_dialog", mock_dialog)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = select_updates({}, console)
        assert result == []
        mock_dialog.assert_not_called()

    def test_dialog_values_shape(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_dialog = MagicMock()
        mock_dialog.return_value.run.return_value = []
        monkeypatch.setattr("installer.flow.update.checkboxlist_dialog", mock_dialog)
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        select_updates(_DIFFS, console)
        values = mock_dialog.call_args.kwargs.get("values", [])
        keys = [v[0] for v in values]
        labels = [v[1] for v in values]
        assert set(keys) == {"proj", "worktree", "router"}
        assert any("1.0.0" in lbl and "1.1.0" in lbl for lbl in labels)
