"""Tests for installer.main — dispatch logic and error handling."""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import MagicMock, patch


from installer.detect import InstallState
from installer.errors import InstallerError, UserCancelled
from installer.main import (
    EXIT_CANCELLED,
    EXIT_ERROR,
    EXIT_SUCCESS,
    _install,
    _reinstall,
    _uninstall,
    _update,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(**overrides) -> argparse.Namespace:
    """Build a minimal args namespace with sensible defaults."""
    defaults = {
        "update": False,
        "reinstall": False,
        "uninstall": False,
        "full_cleanup": False,
        "plugins": None,
        "skip_wizard": True,
        "verbose": False,
        "no_tui": True,
        "branch": None,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ===================================================================
# _install dispatch
# ===================================================================


class TestInstall:
    """Tests for _install()."""

    @patch("installer.main.run_wizard")
    @patch("installer.main.select_plugins", return_value=[])
    @patch("installer.main.load_plugins", return_value=[])
    def test_no_plugins_selected_returns_success(self, _load, _select, _wizard):
        """When no plugins are selected, return success without installing."""
        args = _make_args()
        result = _install(args)
        assert result == EXIT_SUCCESS
        _wizard.assert_not_called()

    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    def test_install_single_plugin_success(
        self, _wizard, _check_mp, _avail, _installed, _install_plugin
    ):
        """Install a single plugin successfully."""
        args = _make_args(plugins=["proj"])
        result = _install(args)
        assert result == EXIT_SUCCESS
        _install_plugin.assert_called_once_with("proj@gh:x/y")

    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=[])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    def test_install_plugin_not_in_marketplace(
        self, _wizard, _check_mp, _avail, _installed, _install_plugin
    ):
        """Plugin not found in marketplace results in failure."""
        args = _make_args(plugins=["nonexistent"])
        result = _install(args)
        assert result == EXIT_ERROR
        _install_plugin.assert_not_called()

    @patch("installer.main.Confirm")
    @patch("installer.main.install_plugin")
    @patch("installer.main.uninstall_plugin")
    @patch("installer.main.get_installed_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    def test_install_already_installed_skip(
        self,
        _wizard,
        _check_mp,
        _avail,
        _installed,
        _uninstall,
        _install_plugin,
        mock_confirm,
    ):
        """Already installed plugin is skipped when user declines reinstall."""
        mock_confirm.ask.return_value = False
        args = _make_args(plugins=["proj"])
        result = _install(args)
        assert result == EXIT_SUCCESS
        _install_plugin.assert_not_called()
        _uninstall.assert_not_called()

    @patch("installer.main.Confirm")
    @patch("installer.main.install_plugin")
    @patch("installer.main.uninstall_plugin")
    @patch("installer.main.get_installed_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    def test_install_already_installed_reinstall(
        self,
        _wizard,
        _check_mp,
        _avail,
        _installed,
        _uninstall,
        _install_plugin,
        mock_confirm,
    ):
        """Already installed plugin is reinstalled when user confirms."""
        mock_confirm.ask.return_value = True
        args = _make_args(plugins=["proj"])
        result = _install(args)
        assert result == EXIT_SUCCESS
        _uninstall.assert_called_once()
        _install_plugin.assert_called_once()

    @patch("installer.main.Confirm")
    @patch("installer.main.install_plugin", side_effect=InstallerError("fail"))
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    def test_install_failure_no_retry(
        self, _wizard, _check_mp, _avail, _installed, _install_plugin, mock_confirm
    ):
        """Installation failure with no retry returns EXIT_ERROR."""
        mock_confirm.ask.return_value = False  # don't retry
        args = _make_args(plugins=["proj"])
        result = _install(args)
        assert result == EXIT_ERROR

    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    def test_install_with_branch_re_adds_marketplace(
        self,
        _wizard,
        _check_mp,
        _avail,
        _installed,
        _install_plugin,
        _remove_mp,
        _add_mp,
    ):
        """--branch flag causes marketplace to be removed and re-added."""
        args = _make_args(plugins=["proj"], branch="dev")
        result = _install(args)
        assert result == EXIT_SUCCESS
        _remove_mp.assert_called_once()
        _add_mp.assert_called_once_with(branch="dev")

    @patch("installer.main.add_marketplace")
    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=False)
    @patch("installer.main.run_wizard")
    def test_install_marketplace_not_registered_adds(
        self, _wizard, _check_mp, _avail, _installed, _install_plugin, _add_mp
    ):
        """Marketplace is auto-added when not registered."""
        args = _make_args(plugins=["proj"])
        _install(args)
        _add_mp.assert_called_once_with(branch=None)


# ===================================================================
# _update dispatch
# ===================================================================


class TestUpdate:
    """Tests for _update()."""

    @patch("installer.main.display_version_diff")
    @patch("installer.main.compare_versions", return_value={})
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_no_installed_plugins(self, mock_detect, _disp, _cmp, _diff):
        """No installed plugins returns success with message."""
        mock_detect.return_value = InstallState(installed_plugins=[])
        args = _make_args(update=True)
        result = _update(args)
        assert result == EXIT_SUCCESS

    @patch("installer.main.display_version_diff")
    @patch("installer.main.compare_versions", return_value={})
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_no_diffs_returns_success(self, mock_detect, _disp, _cmp, _diff):
        """No version diffs means nothing to update."""
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(update=True)
        result = _update(args)
        assert result == EXIT_SUCCESS

    @patch("installer.main.update_plugin")
    @patch("installer.main.display_version_diff")
    @patch("installer.main.compare_versions", return_value={"proj": ("1.0", "1.1")})
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_update_single_plugin_success(
        self, mock_detect, _disp, _cmp, _diff, mock_update
    ):
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(update=True)
        result = _update(args)
        assert result == EXIT_SUCCESS
        mock_update.assert_called_once_with("proj")

    @patch("installer.main.Confirm")
    @patch("installer.main.update_plugin", side_effect=InstallerError("fail"))
    @patch("installer.main.display_version_diff")
    @patch("installer.main.compare_versions", return_value={"proj": ("1.0", "1.1")})
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_update_failure_no_retry(
        self, mock_detect, _disp, _cmp, _diff, mock_update, mock_confirm
    ):
        """Update failure with no retry returns EXIT_ERROR."""
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        mock_confirm.ask.return_value = False
        args = _make_args(update=True)
        result = _update(args)
        assert result == EXIT_ERROR

    @patch("installer.main.update_plugin")
    @patch("installer.main.display_version_diff")
    @patch("installer.main.compare_versions", return_value={"proj": ("1.0", "1.1")})
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_update_with_specific_plugins(
        self, mock_detect, _disp, _cmp, _diff, mock_update
    ):
        """--plugins flag limits which plugins get updated."""
        mock_detect.return_value = InstallState(installed_plugins=["proj", "hooks"])
        args = _make_args(update=True, plugins=["proj"])
        result = _update(args)
        assert result == EXIT_SUCCESS
        mock_update.assert_called_once_with("proj")

    @patch("installer.main.update_plugin")
    @patch("installer.main.display_version_diff")
    @patch(
        "installer.main.compare_versions",
        return_value={"proj": ("1.0", "1.1")},
    )
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_update_plugins_filter_no_match(
        self, mock_detect, _disp, _cmp, _diff, mock_update
    ):
        """--plugins with no matching diffs returns success."""
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(update=True, plugins=["hooks"])  # hooks not in diffs
        result = _update(args)
        assert result == EXIT_SUCCESS
        mock_update.assert_not_called()


# ===================================================================
# _reinstall dispatch
# ===================================================================


class TestReinstall:
    """Tests for _reinstall()."""

    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_no_installed_plugins(self, mock_detect, _disp):
        mock_detect.return_value = InstallState(installed_plugins=[])
        args = _make_args(reinstall=True)
        result = _reinstall(args)
        assert result == EXIT_SUCCESS

    @patch("installer.main.run_wizard")
    @patch("installer.main.install_plugin")
    @patch("installer.main.uninstall_plugin")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_reinstall_success(
        self, mock_detect, _disp, mock_uninstall, mock_install, _wizard
    ):
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(reinstall=True)
        result = _reinstall(args)
        assert result == EXIT_SUCCESS
        mock_uninstall.assert_called_once_with("proj")
        mock_install.assert_called_once_with("proj")

    @patch("installer.main.run_wizard")
    @patch("installer.main.install_plugin")
    @patch("installer.main.uninstall_plugin")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_reinstall_skip_wizard(
        self, mock_detect, _disp, _uninstall, _install, mock_wizard
    ):
        """--skip-wizard prevents wizard from running after reinstall."""
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(reinstall=True, skip_wizard=True)
        _reinstall(args)
        mock_wizard.assert_not_called()

    @patch("installer.main.run_wizard")
    @patch("installer.main.install_plugin")
    @patch("installer.main.uninstall_plugin")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_reinstall_runs_wizard_when_not_skipped(
        self, mock_detect, _disp, _uninstall, _install, mock_wizard
    ):
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(reinstall=True, skip_wizard=False)
        _reinstall(args)
        mock_wizard.assert_called_once_with(["proj"], skip=False)

    @patch("installer.main.Confirm")
    @patch("installer.main.install_plugin", side_effect=InstallerError("fail"))
    @patch("installer.main.uninstall_plugin")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_reinstall_failure_no_retry(
        self, mock_detect, _disp, _uninstall, _install, mock_confirm
    ):
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        mock_confirm.ask.return_value = False
        args = _make_args(reinstall=True)
        result = _reinstall(args)
        assert result == EXIT_ERROR

    @patch("installer.main.install_plugin")
    @patch("installer.main.uninstall_plugin")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_reinstall_with_specific_plugins(
        self, mock_detect, _disp, mock_uninstall, mock_install
    ):
        """--plugins limits reinstall to named plugins."""
        mock_detect.return_value = InstallState(installed_plugins=["proj", "hooks"])
        args = _make_args(reinstall=True, plugins=["hooks"])
        result = _reinstall(args)
        assert result == EXIT_SUCCESS
        mock_uninstall.assert_called_once_with("hooks")
        mock_install.assert_called_once_with("hooks")


# ===================================================================
# _uninstall dispatch
# ===================================================================


class TestUninstall:
    """Tests for _uninstall()."""

    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_no_installed_plugins(self, mock_detect, _disp):
        mock_detect.return_value = InstallState(installed_plugins=[])
        args = _make_args(uninstall=True)
        result = _uninstall(args)
        assert result == EXIT_SUCCESS

    @patch("installer.main.uninstall_plugin")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_uninstall_success(self, mock_detect, _disp, mock_uninstall):
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(uninstall=True)
        result = _uninstall(args)
        assert result == EXIT_SUCCESS
        mock_uninstall.assert_called_once_with("proj")

    @patch("installer.main.cleanup_config_files")
    @patch("installer.main.uninstall_plugin")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_uninstall_with_full_cleanup(
        self, mock_detect, _disp, mock_uninstall, mock_cleanup
    ):
        """--full-cleanup triggers config file removal after uninstall."""
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(uninstall=True, full_cleanup=True)
        result = _uninstall(args)
        assert result == EXIT_SUCCESS
        mock_uninstall.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch("installer.main.cleanup_config_files")
    @patch("installer.main.uninstall_plugin")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_uninstall_without_full_cleanup(
        self, mock_detect, _disp, mock_uninstall, mock_cleanup
    ):
        """Without --full-cleanup, config files are not removed."""
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(uninstall=True, full_cleanup=False)
        result = _uninstall(args)
        assert result == EXIT_SUCCESS
        mock_cleanup.assert_not_called()

    @patch("installer.main.Confirm")
    @patch("installer.main.uninstall_plugin", side_effect=InstallerError("fail"))
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_uninstall_failure_no_retry(
        self, mock_detect, _disp, mock_uninstall, mock_confirm
    ):
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        mock_confirm.ask.return_value = False
        args = _make_args(uninstall=True)
        result = _uninstall(args)
        assert result == EXIT_ERROR

    @patch("installer.main.cleanup_config_files")
    @patch("installer.main.uninstall_plugin")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_uninstall_multiple_plugins(
        self, mock_detect, _disp, mock_uninstall, mock_cleanup
    ):
        """Multiple installed plugins are all uninstalled."""
        mock_detect.return_value = InstallState(
            installed_plugins=["proj", "hooks", "sandbox"]
        )
        args = _make_args(uninstall=True, full_cleanup=True)
        result = _uninstall(args)
        assert result == EXIT_SUCCESS
        assert mock_uninstall.call_count == 3
        mock_cleanup.assert_called_once()


# ===================================================================
# main() dispatch and error handling
# ===================================================================


class TestMain:
    """Tests for main() entry point."""

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main.InstallerApp")
    @patch("installer.main.build_parser")
    def test_main_default_mode_uses_tui(
        self, mock_parser, mock_app_cls, _root, _prereq, _lock, _release
    ):
        """Default (no --no-tui) launches InstallerApp."""
        args = _make_args(no_tui=False)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        result = main()
        assert result == EXIT_SUCCESS
        mock_app_cls.assert_called_once_with(mode="install", args=args)
        mock_app_cls.return_value.run.assert_called_once()

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main._install", return_value=EXIT_SUCCESS)
    @patch("installer.main.build_parser")
    def test_main_no_tui_install(
        self, mock_parser, mock_install, _root, _prereq, _lock, _release
    ):
        """--no-tui routes to _install."""
        args = _make_args(no_tui=True)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        result = main()
        assert result == EXIT_SUCCESS
        mock_install.assert_called_once_with(args)

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main._update", return_value=EXIT_SUCCESS)
    @patch("installer.main.build_parser")
    def test_main_no_tui_update(
        self, mock_parser, mock_update, _root, _prereq, _lock, _release
    ):
        """--no-tui --update routes to _update."""
        args = _make_args(no_tui=True, update=True)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        result = main()
        assert result == EXIT_SUCCESS
        mock_update.assert_called_once_with(args)

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main._reinstall", return_value=EXIT_SUCCESS)
    @patch("installer.main.build_parser")
    def test_main_no_tui_reinstall(
        self, mock_parser, mock_reinstall, _root, _prereq, _lock, _release
    ):
        args = _make_args(no_tui=True, reinstall=True)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        result = main()
        assert result == EXIT_SUCCESS
        mock_reinstall.assert_called_once_with(args)

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main._uninstall", return_value=EXIT_SUCCESS)
    @patch("installer.main.build_parser")
    def test_main_no_tui_uninstall(
        self, mock_parser, mock_uninstall, _root, _prereq, _lock, _release
    ):
        args = _make_args(no_tui=True, uninstall=True)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        result = main()
        assert result == EXIT_SUCCESS
        mock_uninstall.assert_called_once_with(args)

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main._uninstall", return_value=EXIT_SUCCESS)
    @patch("installer.main.build_parser")
    def test_main_full_cleanup_implies_uninstall(
        self, mock_parser, mock_uninstall, _root, _prereq, _lock, _release
    ):
        """--full-cleanup alone implies --uninstall."""
        args = _make_args(no_tui=True, full_cleanup=True, uninstall=False)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        result = main()
        # main() should have set args.uninstall = True
        assert args.uninstall is True
        assert result == EXIT_SUCCESS
        mock_uninstall.assert_called_once_with(args)

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main.build_parser")
    def test_main_keyboard_interrupt(
        self, mock_parser, mock_root, _prereq, _lock, _release
    ):
        """KeyboardInterrupt returns EXIT_CANCELLED."""
        mock_root.side_effect = KeyboardInterrupt()
        args = _make_args()
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        result = main()
        assert result == EXIT_CANCELLED

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main.build_parser")
    def test_main_user_cancelled(
        self, mock_parser, mock_root, _prereq, _lock, _release
    ):
        """UserCancelled returns its exit_code."""
        mock_root.side_effect = UserCancelled("nope")
        args = _make_args()
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        result = main()
        assert result == EXIT_CANCELLED

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main.build_parser")
    def test_main_installer_error(
        self, mock_parser, mock_root, _prereq, _lock, _release
    ):
        """InstallerError returns its exit_code."""
        mock_root.side_effect = InstallerError("boom", exit_code=2)
        args = _make_args()
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        result = main()
        assert result == EXIT_ERROR

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main._install", side_effect=InstallerError("boom"))
    @patch("installer.main.build_parser")
    def test_main_lock_released_on_error(
        self, mock_parser, _install, _root, _prereq, mock_lock, mock_release
    ):
        """Lock is always released in finally block."""
        lock_fh = MagicMock()
        mock_lock.return_value = lock_fh
        args = _make_args(no_tui=True)
        mock_parser.return_value.parse_args.return_value = args
        main()
        mock_release.assert_called_once_with(lock_fh)

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main.InstallerApp")
    @patch("installer.main.build_parser")
    def test_main_tui_update_mode(
        self, mock_parser, mock_app_cls, _root, _prereq, _lock, _release
    ):
        """--update without --no-tui launches TUI in update mode."""
        args = _make_args(no_tui=False, update=True)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        main()
        mock_app_cls.assert_called_once_with(mode="update", args=args)

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main.InstallerApp")
    @patch("installer.main.build_parser")
    def test_main_tui_reinstall_mode(
        self, mock_parser, mock_app_cls, _root, _prereq, _lock, _release
    ):
        args = _make_args(no_tui=False, reinstall=True)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        main()
        mock_app_cls.assert_called_once_with(mode="reinstall", args=args)

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main.InstallerApp")
    @patch("installer.main.build_parser")
    def test_main_tui_uninstall_mode(
        self, mock_parser, mock_app_cls, _root, _prereq, _lock, _release
    ):
        args = _make_args(no_tui=False, uninstall=True)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        main()
        mock_app_cls.assert_called_once_with(mode="uninstall", args=args)


# ===================================================================
# app.py unit-testable helpers
# ===================================================================


class TestInstallerAppHelpers:
    """Tests for InstallerApp utility methods that don't need a running app."""

    def test_init_defaults(self):
        """InstallerApp stores mode and args correctly."""
        from installer.app import InstallerApp

        app = InstallerApp(mode="install", args=None)
        assert app.mode == "install"
        assert app.installer_args is None
        assert app.selected_plugins == []
        assert app.wizard_config is None
        assert app._branch is None

    def test_init_with_branch(self):
        """InstallerApp extracts branch from args."""
        from installer.app import InstallerApp

        args = _make_args(branch="dev")
        app = InstallerApp(mode="install", args=args)
        assert app._branch == "dev"

    def test_build_detection_rows(self):
        """_build_detection_rows produces correct rows."""
        from installer.app import InstallerApp

        app = InstallerApp(mode="update")
        state = InstallState(
            installed_plugins=["proj", "hooks"],
            cache_dir=Path("/nonexistent"),
        )
        with (
            patch(
                "installer.app._read_marketplace_versions",
                return_value={"proj": "1.1", "sandbox": "0.2"},
            ),
            patch("installer.app._read_installed_version", return_value="1.0"),
        ):
            rows = app._build_detection_rows(state)

        plugin_names = [r.plugin for r in rows]
        assert "proj" in plugin_names
        assert "hooks" in plugin_names
        assert "sandbox" in plugin_names

    def test_proj_plugins_constant(self):
        """_PROJ_PLUGINS includes expected plugins."""
        from installer.app import InstallerApp

        assert "proj" in InstallerApp._PROJ_PLUGINS
        assert "hooks" in InstallerApp._PROJ_PLUGINS
        assert "sandbox" in InstallerApp._PROJ_PLUGINS
        assert "worktree" not in InstallerApp._PROJ_PLUGINS

    def test_on_plugins_selected_empty_exits(self):
        """Selecting no plugins calls exit."""
        from installer.app import InstallerApp

        app = InstallerApp(mode="install")
        app.exit = MagicMock()
        app._on_plugins_selected([])
        app.exit.assert_called_once()

    def test_on_detection_done_false_exits(self):
        """Declining detection screen calls exit."""
        from installer.app import InstallerApp

        app = InstallerApp(mode="update")
        app.exit = MagicMock()
        app._on_detection_done(False)
        app.exit.assert_called_once()

    def test_on_update_selected_empty_exits(self):
        """Empty update selection calls exit."""
        from installer.app import InstallerApp

        app = InstallerApp(mode="update")
        app._state = InstallState()
        app.exit = MagicMock()
        app._on_update_selected([])
        app.exit.assert_called_once()

    def test_on_wizard_complete_none_goes_back(self):
        """Cancelling wizard pushes plugin select screen again."""
        from installer.app import InstallerApp

        app = InstallerApp(mode="install")
        app.push_screen = MagicMock()
        app._on_wizard_complete(None)
        app.push_screen.assert_called_once()

    def test_write_config_files_worktree(self, mock_home):
        """_write_config_files creates worktree.yaml when worktree is selected."""
        from installer.app import InstallerApp

        app = InstallerApp(mode="install")
        app.selected_plugins = ["worktree"]
        config = {
            "tracking_dir": str(mock_home / "tracking"),
            "projects_base_dir": str(mock_home / "projects"),
            "sandbox_integration": True,
            "zoxide_integration": False,
            "worktree_dir": str(mock_home / "worktrees"),
        }
        app._write_config_files(config)
        wt_yaml = mock_home / ".claude" / "worktree.yaml"
        assert wt_yaml.exists()
        content = wt_yaml.read_text()
        assert "worktrees" in content

    def test_write_config_files_proj(self, mock_home):
        """_write_config_files creates proj.yaml when proj plugin is selected."""
        from installer.app import InstallerApp

        app = InstallerApp(mode="install")
        app.selected_plugins = ["proj"]
        config = {
            "tracking_dir": str(mock_home / "tracking"),
            "projects_base_dir": str(mock_home / "projects"),
            "sandbox_integration": True,
            "zoxide_integration": False,
        }
        app._write_config_files(config)
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        assert proj_yaml.exists()
        content = proj_yaml.read_text()
        assert "tracking_dir" in content
        assert "sandbox_integration: true" in content

    def test_write_config_files_with_integrations(self, mock_home):
        """_write_config_files writes sync sections for integrations."""
        from installer.app import InstallerApp

        app = InstallerApp(mode="install")
        app.selected_plugins = ["proj", "todoist", "jira"]
        config = {
            "tracking_dir": str(mock_home / "tracking"),
            "projects_base_dir": str(mock_home / "projects"),
            "sandbox_integration": False,
            "zoxide_integration": False,
            "todoist_enabled": True,
            "jira_enabled": True,
            "jira_default_user": "testuser",
        }
        app._write_config_files(config)
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        content = proj_yaml.read_text()
        assert "todoist:" in content
        assert "enabled: true" in content
        assert "jira:" in content
        assert "default_user: testuser" in content
