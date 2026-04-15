"""Verify sandbox tools are registered in proj MCP server after fold."""

from __future__ import annotations


def _tool_names() -> list[str]:
    from server.tools.sandbox import (
        sandbox_add_write_path,
        sandbox_batch_revoke,
        sandbox_batch_setup,
        sandbox_check,
        sandbox_list,
        sandbox_reconcile,
        sandbox_remove_write_path,
        sandbox_set_deny,
    )

    return [
        fn.__name__
        for fn in (
            sandbox_add_write_path,
            sandbox_remove_write_path,
            sandbox_set_deny,
            sandbox_batch_setup,
            sandbox_batch_revoke,
            sandbox_list,
            sandbox_check,
            sandbox_reconcile,
        )
    ]


def test_sandbox_tool_functions_importable() -> None:
    """All 8 sandbox tool functions importable from proj server."""
    names = _tool_names()
    assert "sandbox_batch_setup" in names
    assert "sandbox_batch_revoke" in names
    assert "sandbox_add_write_path" in names
    assert "sandbox_remove_write_path" in names
    assert "sandbox_set_deny" in names
    assert "sandbox_list" in names
    assert "sandbox_check" in names
    assert "sandbox_reconcile" in names
    assert len(names) == 8


def test_sandbox_lib_importable() -> None:
    """sandbox storage + models importable from proj lib."""
    from server.lib.sandbox import storage
    from server.lib.sandbox.models import SettingsFile

    assert callable(storage.load)
    assert callable(storage.save)
    assert SettingsFile is not None
