"""Integration tests for --local-marketplace wiring in TUI flow."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch

from installer.flow.installer_flow import _run_install, _run_reinstall


def _make_args(**overrides) -> argparse.Namespace:
    defaults = {
        "reinstall": False,
        "uninstall": False,
        "full_cleanup": False,
        "plugins": None,
        "skip_wizard": True,
        "verbose": False,
        "no_tui": False,
        "branch": None,
        "local_marketplace": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


class TestRunInstallLocalMarketplace:
    @patch("installer.flow.installer_flow.select_plugin_actions", return_value=[])
    @patch("installer.flow.installer_flow.build_plugin_status_list", return_value=[])
    @patch("installer.flow.installer_flow.add_marketplace")
    @patch("installer.flow.installer_flow.remove_marketplace")
    @patch(
        "installer.flow.installer_flow.check_marketplace_registered", return_value=False
    )
    @patch("installer.main.ensure_local_clone")
    def test_run_install_local_marketplace_not_registered(
        self,
        mock_ensure,
        _check_mp,
        mock_remove,
        mock_add,
        _status,
        _actions,
    ):
        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        args = _make_args(local_marketplace=True)
        console = MagicMock()
        exit_code = _run_install(args, console)
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)
        mock_remove.assert_not_called()
        assert exit_code == 0

    @patch("installer.flow.installer_flow.select_plugin_actions", return_value=[])
    @patch("installer.flow.installer_flow.build_plugin_status_list", return_value=[])
    @patch("installer.flow.installer_flow.add_marketplace")
    @patch("installer.flow.installer_flow.remove_marketplace")
    @patch(
        "installer.flow.installer_flow.check_marketplace_registered", return_value=True
    )
    @patch("installer.main.ensure_local_clone")
    def test_run_install_local_marketplace_already_registered_reregisters(
        self,
        mock_ensure,
        _check_mp,
        mock_remove,
        mock_add,
        _status,
        _actions,
    ):
        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        args = _make_args(local_marketplace=True)
        console = MagicMock()
        exit_code = _run_install(args, console)
        mock_remove.assert_called_once()
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)
        assert exit_code == 0

    @patch("installer.flow.installer_flow.select_plugin_actions", return_value=[])
    @patch("installer.flow.installer_flow.build_plugin_status_list", return_value=[])
    @patch("installer.flow.installer_flow.add_marketplace")
    @patch("installer.flow.installer_flow.remove_marketplace")
    @patch(
        "installer.flow.installer_flow.check_marketplace_registered", return_value=True
    )
    @patch("installer.main.ensure_local_clone")
    def test_run_install_default_no_reregister(
        self,
        mock_ensure,
        _check_mp,
        mock_remove,
        mock_add,
        _status,
        _actions,
    ):
        # No --local-marketplace, no --branch → marketplace stays as-is
        args = _make_args()
        console = MagicMock()
        _run_install(args, console)
        mock_ensure.assert_not_called()
        mock_remove.assert_not_called()
        mock_add.assert_not_called()


class TestRunReinstallLocalMarketplace:
    @patch("installer.flow.installer_flow._post_execute_cleanup")
    @patch("installer.flow.installer_flow._execute_and_report", return_value=0)
    @patch(
        "installer.flow.installer_flow._name_to_id_map",
        return_value={"proj": "proj@claude-project-manager"},
    )
    @patch("installer.flow.installer_flow.add_marketplace")
    @patch("installer.flow.installer_flow.remove_marketplace")
    @patch("installer.main.ensure_local_clone")
    def test_run_reinstall_local_marketplace_reregisters(
        self,
        mock_ensure,
        mock_remove,
        mock_add,
        _name_map,
        _execute,
        _post_cleanup,
    ):
        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        pre_state = MagicMock(installed_plugins=["proj"])
        args = _make_args(reinstall=True, local_marketplace=True)
        console = MagicMock()
        exit_code = _run_reinstall(
            args, pre_state, {"full_cleanup": False}, [], console
        )
        mock_remove.assert_called_once()
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)
        assert exit_code == 0

    @patch("installer.flow.installer_flow._post_execute_cleanup")
    @patch("installer.flow.installer_flow._execute_and_report", return_value=0)
    @patch(
        "installer.flow.installer_flow._name_to_id_map",
        return_value={"proj": "proj@claude-project-manager"},
    )
    @patch("installer.flow.installer_flow.add_marketplace")
    @patch("installer.flow.installer_flow.remove_marketplace")
    @patch("installer.main.ensure_local_clone")
    def test_run_reinstall_default_no_marketplace_touch(
        self,
        mock_ensure,
        mock_remove,
        mock_add,
        _name_map,
        _execute,
        _post_cleanup,
    ):
        # No --local-marketplace, no --branch → marketplace untouched
        pre_state = MagicMock(installed_plugins=["proj"])
        args = _make_args(reinstall=True)
        console = MagicMock()
        _run_reinstall(args, pre_state, {"full_cleanup": False}, [], console)
        mock_ensure.assert_not_called()
        mock_remove.assert_not_called()
        mock_add.assert_not_called()


class TestRunInstallClonFailure:
    @patch("installer.flow.installer_flow.select_plugin_actions", return_value=[])
    @patch("installer.flow.installer_flow.build_plugin_status_list", return_value=[])
    @patch(
        "installer.flow.installer_flow.check_marketplace_registered", return_value=False
    )
    @patch("installer.main.ensure_local_clone")
    def test_run_install_local_clone_failure_returns_1(
        self,
        mock_ensure,
        _check_mp,
        _status,
        _actions,
    ):
        """ensure_local_clone failure in _run_install → clean err + exit 1."""
        from installer.errors import InstallerError

        mock_ensure.side_effect = InstallerError("git not found on PATH")
        args = _make_args(local_marketplace=True)
        console = MagicMock()
        exit_code = _run_install(args, console)
        assert exit_code == 1


class TestRunReinstallCloneFailure:
    @patch("installer.flow.installer_flow._post_execute_cleanup")
    @patch("installer.flow.installer_flow._execute_and_report", return_value=0)
    @patch(
        "installer.flow.installer_flow._name_to_id_map",
        return_value={"proj": "proj@claude-project-manager"},
    )
    @patch("installer.flow.installer_flow.add_marketplace")
    @patch("installer.flow.installer_flow.remove_marketplace")
    @patch("installer.main.ensure_local_clone")
    def test_run_reinstall_local_clone_failure_returns_1(
        self,
        mock_ensure,
        mock_remove,
        mock_add,
        _name_map,
        _execute,
        _post_cleanup,
    ):
        """ensure_local_clone failure in _run_reinstall → clean err + exit 1."""
        from installer.errors import InstallerError

        mock_ensure.side_effect = InstallerError("git not found on PATH")
        pre_state = MagicMock(installed_plugins=["proj"])
        args = _make_args(reinstall=True, local_marketplace=True)
        console = MagicMock()
        exit_code = _run_reinstall(
            args, pre_state, {"full_cleanup": False}, [], console
        )
        assert exit_code == 1
        mock_remove.assert_not_called()
        mock_add.assert_not_called()
