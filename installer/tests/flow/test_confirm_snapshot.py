# installer/tests/flow/test_confirm_snapshot.py
"""Syrupy snapshots for confirm_with_options flow helper."""

import pytest
from rich.console import Console

from installer.flow.confirm import ConfirmOption, confirm_with_options


def test_confirm_primary_snapshot(snapshot, monkeypatch: pytest.MonkeyPatch) -> None:
    """Snapshot of confirm dialog with primary variant and options."""
    monkeypatch.setattr("installer.flow.confirm.ask_yn", lambda *a, **k: True)
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    confirm_with_options(
        title="Reinstall?",
        message="This will reinstall all plugins.",
        options=[ConfirmOption(key="reset", label="Reset configs", default=False)],
        console=console,
    )
    assert console.export_text() == snapshot


def test_confirm_error_variant_snapshot(
    snapshot, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Snapshot of confirm dialog with error variant, no options."""
    monkeypatch.setattr("installer.flow.confirm.ask_yn", lambda *a, **k: False)
    console = Console(record=True, width=80, force_terminal=False, no_color=True)
    confirm_with_options(
        title="Uninstall?",
        message="Permanently remove all plugins.",
        options=[],
        console=console,
        variant="error",
    )
    assert console.export_text() == snapshot
