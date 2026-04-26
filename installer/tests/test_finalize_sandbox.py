"""Unit tests for installer.flow.installer_flow._finalize_sandbox.

The step reconciles ~/.claude/settings.json MCP allow rules with the
union of (selected_plugins from this run, get_installed_plugins() from
the cache). Failures are warnings only — install must NOT abort.
"""

from __future__ import annotations

import argparse
from unittest.mock import MagicMock, patch

from rich.console import Console


def _args() -> argparse.Namespace:
    return argparse.Namespace(
        reinstall=False,
        uninstall=False,
        plugins=None,
        skip_wizard=True,
        verbose=False,
        no_tui=True,
        branch=None,
        local_marketplace=False,
    )


class TestFinalizeSandbox:
    def test_calls_reconcile_with_union_of_selected_and_installed(self):
        """selected = ['proj']; installed = ['worktree'] → expected_servers
        contains both plugin_proj_proj AND plugin_worktree_worktree."""
        from installer.flow.installer_flow import _finalize_sandbox

        with (
            patch(
                "installer.flow.installer_flow._name_to_id_map",
                return_value={"worktree": "worktree@cpm"},
            ),
            patch("sandbox.reconcile_settings") as mock_reconcile,
        ):
            mock_reconcile.return_value = MagicMock(
                added=2, removed=0, stale_removed=[]
            )
            console = Console(width=80, force_terminal=False, no_color=True)
            _finalize_sandbox(_args(), ["proj"], console)

        mock_reconcile.assert_called_once()
        call_args = mock_reconcile.call_args
        expected_servers = call_args.kwargs.get("expected_servers") or call_args.args[0]
        assert "plugin_proj_proj" in expected_servers
        assert "plugin_worktree_worktree" in expected_servers

    def test_unmapped_plugin_warning(self):
        """A plugin name not in PLUGIN_TO_MCP_SERVER → warning printed,
        plugin skipped from expected_servers, install continues."""
        from io import StringIO

        from installer.flow.installer_flow import _finalize_sandbox

        buf = StringIO()
        console = Console(file=buf, width=80, force_terminal=False, no_color=True)

        with (
            patch(
                "installer.flow.installer_flow._name_to_id_map",
                return_value={},
            ),
            patch("sandbox.reconcile_settings") as mock_reconcile,
        ):
            mock_reconcile.return_value = MagicMock(
                added=0, removed=0, stale_removed=[]
            )
            _finalize_sandbox(_args(), ["unknown-plugin"], console)

        assert "unknown-plugin" in buf.getvalue()
        assert "Skipped" in buf.getvalue() or "unmapped" in buf.getvalue()

    def test_oserror_is_yellow_warning_not_abort(self):
        """reconcile_settings raising OSError → yellow warning, no exception."""
        from io import StringIO

        from installer.flow.installer_flow import _finalize_sandbox

        buf = StringIO()
        console = Console(file=buf, width=80, force_terminal=False, no_color=True)

        with (
            patch(
                "installer.flow.installer_flow._name_to_id_map",
                return_value={},
            ),
            patch(
                "sandbox.reconcile_settings",
                side_effect=OSError("disk full"),
            ),
        ):
            # Must not raise — failures are warnings only.
            _finalize_sandbox(_args(), ["proj"], console)

        assert "Failed to reconcile" in buf.getvalue() or "disk full" in buf.getvalue()

    def test_counter_message_shows_added_and_removed(self):
        """Non-zero added/removed counts → green ✓ message with counts."""
        from io import StringIO

        from installer.flow.installer_flow import _finalize_sandbox

        buf = StringIO()
        console = Console(file=buf, width=80, force_terminal=False, no_color=True)

        with (
            patch(
                "installer.flow.installer_flow._name_to_id_map",
                return_value={},
            ),
            patch("sandbox.reconcile_settings") as mock_reconcile,
        ):
            mock_reconcile.return_value = MagicMock(
                added=3,
                removed=1,
                stale_removed=["plugin_old_old"],
            )
            _finalize_sandbox(_args(), ["proj"], console)

        out = buf.getvalue()
        assert "added 3" in out
        assert "removed 1" in out
        assert "plugin_old_old" in out
