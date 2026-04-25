"""Tests for installer.main — dispatch logic and error handling."""

from __future__ import annotations

import argparse
from unittest.mock import ANY, MagicMock, patch


from installer.detect import InstallState
from installer.errors import InstallerError, UserCancelled
from installer.main import (
    EXIT_CANCELLED,
    EXIT_ERROR,
    EXIT_SUCCESS,
    _install,
    _reinstall,
    _uninstall,
    main,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_args(**overrides) -> argparse.Namespace:
    """Build a minimal args namespace with sensible defaults."""
    defaults = {
        "reinstall": False,
        "uninstall": False,
        "full_cleanup": False,
        "plugins": None,
        "skip_wizard": True,
        "verbose": False,
        "no_tui": True,
        "branch": None,
        "local_marketplace": False,
    }
    defaults.update(overrides)
    return argparse.Namespace(**defaults)


# ===================================================================
# _resolve_marketplace_source
# ===================================================================


from installer.main import _resolve_marketplace_source  # noqa: E402
from installer.plugin_cli import MARKETPLACE_SOURCE  # noqa: E402


class TestResolveMarketplaceSource:
    def test_default_uses_github_short_ref(self):
        args = _make_args()
        source, branch = _resolve_marketplace_source(args)
        assert source == MARKETPLACE_SOURCE
        assert branch is None

    def test_branch_without_local_passes_through(self):
        args = _make_args(branch="dev")
        source, branch = _resolve_marketplace_source(args)
        assert source == MARKETPLACE_SOURCE
        assert branch == "dev"

    @patch("installer.main.ensure_local_clone")
    def test_local_marketplace_returns_local_path_and_no_branch(self, mock_ensure):
        from pathlib import Path

        mock_ensure.return_value = Path("/home/x/.cache/cpm/local-marketplace")
        args = _make_args(local_marketplace=True)
        source, branch = _resolve_marketplace_source(args)
        mock_ensure.assert_called_once_with(branch=None, console=ANY)
        assert source == "/home/x/.cache/cpm/local-marketplace"
        assert branch is None

    @patch("installer.main.ensure_local_clone")
    def test_local_marketplace_passes_branch_to_ensure_clone(self, mock_ensure):
        from pathlib import Path

        mock_ensure.return_value = Path("/home/x/.cache/cpm/local-marketplace")
        args = _make_args(local_marketplace=True, branch="dev")
        source, branch = _resolve_marketplace_source(args)
        mock_ensure.assert_called_once_with(branch="dev", console=ANY)
        assert source == "/home/x/.cache/cpm/local-marketplace"
        # Branch returned as None because clone is already on that branch
        assert branch is None


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

    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    def test_install_already_installed_is_skipped(
        self,
        _wizard,
        _check_mp,
        _avail,
        _installed,
        _install_plugin,
    ):
        """Already installed plugin is always skipped — use --reinstall to reinstall."""
        args = _make_args(plugins=["proj"])
        result = _install(args)
        assert result == EXIT_SUCCESS
        _install_plugin.assert_not_called()

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
        _add_mp.assert_called_once_with(source=MARKETPLACE_SOURCE, branch="dev")

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
        _add_mp.assert_called_once_with(source=MARKETPLACE_SOURCE, branch=None)

    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch(
        "installer.main.get_available_plugins",
        return_value=["proj@claude-project-manager"],
    )
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.check_marketplace_registered", return_value=False)
    @patch("installer.main.run_wizard")
    @patch("installer.main.ensure_local_clone")
    def test_install_with_local_marketplace_adds_local_path(
        self,
        mock_ensure,
        _wizard,
        _check_mp,
        mock_remove,
        mock_add,
        _avail,
        _installed,
        _install_plugin,
    ):
        from pathlib import Path

        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        args = _make_args(plugins=["proj"], local_marketplace=True)
        result = _install(args)
        assert result == EXIT_SUCCESS
        mock_ensure.assert_called_once_with(branch=None, console=ANY)
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)
        mock_remove.assert_not_called()

    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch(
        "installer.main.get_available_plugins",
        return_value=["proj@claude-project-manager"],
    )
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    @patch("installer.main.ensure_local_clone")
    def test_install_local_marketplace_when_already_registered_removes_and_readds(
        self,
        mock_ensure,
        _wizard,
        _check_mp,
        mock_remove,
        mock_add,
        _avail,
        _installed,
        _install_plugin,
    ):
        from pathlib import Path

        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        args = _make_args(plugins=["proj"], local_marketplace=True)
        _install(args)
        mock_remove.assert_called_once()
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)

    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch(
        "installer.main.get_available_plugins",
        return_value=["proj@claude-project-manager"],
    )
    @patch("installer.main.add_marketplace")
    @patch("installer.main.check_marketplace_registered", return_value=False)
    @patch("installer.main.run_wizard")
    @patch("installer.main.ensure_local_clone")
    def test_install_local_marketplace_with_branch_passes_branch_to_ensure(
        self,
        mock_ensure,
        _wizard,
        _check_mp,
        mock_add,
        _avail,
        _installed,
        _install_plugin,
    ):
        from pathlib import Path

        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        args = _make_args(plugins=["proj"], local_marketplace=True, branch="dev")
        _install(args)
        mock_ensure.assert_called_once_with(branch="dev", console=ANY)
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)

    @patch("installer.main.ensure_local_clone")
    def test_install_local_marketplace_clone_failure_returns_error(self, mock_ensure):
        """ensure_local_clone failure → clean error + EXIT_ERROR, not uncaught raise."""
        mock_ensure.side_effect = InstallerError("git not found on PATH")
        args = _make_args(plugins=["proj"], local_marketplace=True)
        # Should NOT raise — should return EXIT_ERROR w/ clean message
        result = _install(args)
        assert result == EXIT_ERROR

    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    def test_install_skip_wizard_still_creates_shared_venv(
        self,
        _wizard,
        _check_mp,
        _avail,
        _installed,
        _install_plugin,
        _add_mp,
        mock_ensure,
        tmp_path,
        monkeypatch,
    ):
        """--skip-wizard bypasses the wizard step; main.py must still
        call ensure_shared_venv as a finalize step."""
        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target)

        args = _make_args(plugins=["proj"], skip_wizard=True)
        result = _install(args)
        assert result == EXIT_SUCCESS
        mock_ensure.assert_called_with(target)

    @patch("installer.main.run_wizard")
    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    def test_install_wizard_path_kills_before_run_wizard(
        self,
        _check_mp,
        _avail,
        _installed,
        _install_plugin,
        mock_wizard,
    ):
        """Non --skip-wizard install: prompt_kill_stale_sessions called
        before run_wizard (which itself triggers shared-venv build via
        _create_shared_venv_step)."""
        from unittest.mock import MagicMock as _MagicMock

        parent = _MagicMock()
        parent.run_wizard = mock_wizard
        with patch(
            "installer.flow.kill_stale.prompt_kill_stale_sessions",
            parent.prompt_kill_stale_sessions,
        ):
            args = _make_args(plugins=["proj"], skip_wizard=False)
            _install(args)
        names = [c[0] for c in parent.mock_calls]
        kill_idx = names.index("prompt_kill_stale_sessions")
        wizard_idx = names.index("run_wizard")
        assert kill_idx < wizard_idx, (
            f"prompt_kill_stale_sessions must precede run_wizard; got {names}"
        )

    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.main.install_plugin")
    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.get_available_plugins", return_value=["proj@gh:x/y"])
    @patch("installer.main.check_marketplace_registered", return_value=True)
    @patch("installer.main.run_wizard")
    def test_install_skip_wizard_kills_before_ensure_shared_venv(
        self,
        _wizard,
        _check_mp,
        _avail,
        _installed,
        _install_plugin,
        mock_ensure,
        tmp_path,
        monkeypatch,
    ):
        """--skip-wizard install: prompt_kill_stale_sessions called before
        ensure_shared_venv in the belt-and-suspenders block."""
        from unittest.mock import MagicMock as _MagicMock

        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target)

        parent = _MagicMock()
        parent.ensure_shared_venv = mock_ensure
        with patch(
            "installer.flow.kill_stale.prompt_kill_stale_sessions",
            parent.prompt_kill_stale_sessions,
        ):
            args = _make_args(plugins=["proj"], skip_wizard=True)
            _install(args)
        names = [c[0] for c in parent.mock_calls]
        kill_idx = names.index("prompt_kill_stale_sessions")
        ensure_idx = names.index("ensure_shared_venv")
        assert kill_idx < ensure_idx, (
            f"prompt_kill_stale_sessions must precede ensure_shared_venv; got {names}"
        )


# ===================================================================
# _reinstall dispatch
# ===================================================================


class TestReinstall:
    """Tests for _reinstall()."""

    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_no_installed_plugins(self, mock_detect, _disp, _gip):
        mock_detect.return_value = InstallState(installed_plugins=[])
        args = _make_args(reinstall=True)
        result = _reinstall(args)
        assert result == EXIT_SUCCESS

    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.run_wizard")
    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_reinstall_success(
        self,
        mock_detect,
        _disp,
        mock_remove_mp,
        mock_add_mp,
        mock_install,
        _wizard,
        _gip,
    ):
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(reinstall=True)
        result = _reinstall(args)
        assert result == EXIT_SUCCESS
        mock_remove_mp.assert_called_once()
        mock_add_mp.assert_called_once_with(source=MARKETPLACE_SOURCE, branch=None)
        mock_install.assert_called_once_with("proj")

    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.run_wizard")
    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_reinstall_skip_wizard(
        self, mock_detect, _disp, _remove_mp, _add_mp, _install, mock_wizard, _gip
    ):
        """--skip-wizard prevents wizard from running after reinstall."""
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(reinstall=True, skip_wizard=True)
        _reinstall(args)
        mock_wizard.assert_not_called()

    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.run_wizard")
    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_reinstall_runs_wizard_when_not_skipped(
        self, mock_detect, _disp, _remove_mp, _add_mp, _install, mock_wizard, _gip
    ):
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(reinstall=True, skip_wizard=False)
        _reinstall(args)
        mock_wizard.assert_called_once_with(["proj"], skip=False, args=args)

    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.Confirm")
    @patch("installer.main.install_plugin", side_effect=InstallerError("fail"))
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_reinstall_failure_no_retry(
        self, mock_detect, _disp, _remove_mp, _add_mp, _install, mock_confirm, _gip
    ):
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        mock_confirm.ask.return_value = False
        args = _make_args(reinstall=True)
        result = _reinstall(args)
        assert result == EXIT_ERROR

    @patch("installer.main.get_installed_plugins", return_value=["proj", "hooks"])
    @patch("installer.main.run_wizard")
    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_reinstall_always_reinstalls_all_ignores_plugins_arg(
        self, mock_detect, _disp, _remove_mp, _add_mp, mock_install, _wizard, _gip
    ):
        """--plugins arg is ignored for reinstall — always reinstalls all installed."""
        mock_detect.return_value = InstallState(installed_plugins=["proj", "hooks"])
        args = _make_args(reinstall=True, plugins=["hooks"])
        result = _reinstall(args)
        assert result == EXIT_SUCCESS
        assert mock_install.call_count == 2  # both proj and hooks reinstalled

    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.scan_stale_cache", side_effect=FileNotFoundError("skip"))
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing", return_value=InstallState())
    @patch(
        "installer.main.get_installed_plugins",
        return_value=["proj@claude-project-manager"],
    )
    @patch("installer.main.run_wizard")
    @patch("installer.main.ensure_local_clone")
    def test_reinstall_with_local_marketplace_adds_local_path(
        self,
        mock_ensure,
        _wizard,
        _installed,
        _detect,
        _display,
        _scan,
        mock_remove,
        mock_add,
        _install_plugin,
    ):
        from pathlib import Path

        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        args = _make_args(reinstall=True, local_marketplace=True)
        result = _reinstall(args)
        mock_remove.assert_called_once()
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)
        assert result == EXIT_SUCCESS

    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.scan_stale_cache", side_effect=FileNotFoundError("skip"))
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing", return_value=InstallState())
    @patch(
        "installer.main.get_installed_plugins",
        return_value=["proj@claude-project-manager"],
    )
    @patch("installer.main.run_wizard")
    @patch("installer.main.ensure_local_clone")
    def test_reinstall_local_marketplace_with_branch(
        self,
        mock_ensure,
        _wizard,
        _installed,
        _detect,
        _display,
        _scan,
        mock_remove,
        mock_add,
        _install_plugin,
    ):
        from pathlib import Path

        mock_ensure.return_value = Path("/home/x/.cache/cpm/mk")
        args = _make_args(reinstall=True, local_marketplace=True, branch="dev")
        _reinstall(args)
        mock_ensure.assert_called_once_with(branch="dev", console=ANY)
        mock_add.assert_called_once_with(source="/home/x/.cache/cpm/mk", branch=None)

    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.scan_stale_cache", side_effect=FileNotFoundError("skip"))
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing", return_value=InstallState())
    @patch(
        "installer.main.get_installed_plugins",
        return_value=["proj@claude-project-manager"],
    )
    @patch("installer.main.run_wizard")
    def test_reinstall_with_branch_only(
        self,
        _wizard,
        _installed,
        _detect,
        _display,
        _scan,
        mock_remove,
        mock_add,
        _install_plugin,
    ):
        args = _make_args(reinstall=True, branch="dev")
        _reinstall(args)
        mock_remove.assert_called_once()
        mock_add.assert_called_once_with(source=MARKETPLACE_SOURCE, branch="dev")

    @patch(
        "installer.main.get_installed_plugins",
        return_value=["proj@claude-project-manager"],
    )
    @patch("installer.main.detect_existing", return_value=InstallState())
    @patch("installer.main.display_detection")
    @patch("installer.main.ensure_local_clone")
    def test_reinstall_local_marketplace_clone_failure_returns_error(
        self,
        mock_ensure,
        _display,
        _detect,
        _installed,
    ):
        """ensure_local_clone failure → clean error + EXIT_ERROR, not uncaught raise."""
        mock_ensure.side_effect = InstallerError("git not found on PATH")
        args = _make_args(reinstall=True, local_marketplace=True)
        result = _reinstall(args)
        assert result == EXIT_ERROR


def test_reinstall_prunes_stale_cache_before_install(monkeypatch, tmp_path, capsys):
    """_reinstall runs scan + prune_stale_versions + prune_orphaned_plugins before install loop."""
    import installer.main as main_mod

    # Set up cache with stale versions + orphan
    cache = tmp_path / "cache"
    cache.mkdir()
    for v in ("3.0.0", "4.0.0", "5.0.0"):
        (cache / "proj" / v).mkdir(parents=True)
    (cache / "sandbox" / "1.0.0").mkdir(parents=True)  # orphan

    # Set up marketplace
    mp = tmp_path / "marketplace.json"
    mp.write_text('{"plugins": [{"name": "proj"}]}')

    # Monkeypatch path resolvers
    monkeypatch.setattr(
        "installer.main._cache_dir_for_reinstall", lambda: cache, raising=False
    )
    monkeypatch.setattr(
        "installer.main._marketplace_path_for_reinstall", lambda: mp, raising=False
    )

    # Auto-confirm orphan removal
    monkeypatch.setattr("rich.prompt.Confirm.ask", lambda *a, **kw: True)

    # Stub downstream calls
    monkeypatch.setattr(
        main_mod, "install_plugin", lambda *a, **kw: None, raising=False
    )
    monkeypatch.setattr(
        main_mod, "remove_marketplace", lambda *a, **kw: None, raising=False
    )
    monkeypatch.setattr(
        main_mod, "add_marketplace", lambda *a, **kw: None, raising=False
    )
    monkeypatch.setattr(
        main_mod,
        "get_installed_plugins",
        lambda: ["proj@claude-project-manager"],
        raising=False,
    )
    monkeypatch.setattr(
        main_mod,
        "detect_existing",
        lambda: InstallState(installed_plugins=[]),
        raising=False,
    )
    monkeypatch.setattr(
        main_mod, "display_detection", lambda *a, **kw: None, raising=False
    )

    import argparse

    args = argparse.Namespace(
        reinstall=True, plugins=None, skip_wizard=True, branch=None
    )
    main_mod._reinstall(args)

    # Stale versions pruned (only newest kept)
    assert (cache / "proj" / "5.0.0").is_dir()
    assert not (cache / "proj" / "3.0.0").exists()
    assert not (cache / "proj" / "4.0.0").exists()
    # Orphan removed
    assert not (cache / "sandbox").exists()


class TestReinstallSharedVenv:
    """_reinstall must finalize the shared venv just like _install."""

    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.scan_stale_cache", side_effect=FileNotFoundError("skip"))
    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    @patch("installer.main.run_wizard")
    def test_skip_wizard_still_creates_shared_venv(
        self,
        _wizard,
        mock_detect,
        _disp,
        _gip,
        _scan,
        _remove_mp,
        _add_mp,
        _install_plugin,
        mock_ensure,
        tmp_path,
        monkeypatch,
    ):
        """--skip-wizard reinstall must fire ensure_shared_venv directly,
        mirroring _install's belt-and-suspenders block."""
        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target)
        mock_detect.return_value = InstallState(installed_plugins=["proj"])

        args = _make_args(reinstall=True, skip_wizard=True)
        result = _reinstall(args)

        assert result == EXIT_SUCCESS
        mock_ensure.assert_any_call(target)

    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.main.ensure_local_clone")
    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.scan_stale_cache", side_effect=FileNotFoundError("skip"))
    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    @patch("installer.main.run_wizard")
    def test_skip_wizard_local_marketplace_creates_local_clone_venv(
        self,
        _wizard,
        mock_detect,
        _disp,
        _gip,
        _scan,
        _remove_mp,
        _add_mp,
        _install_plugin,
        mock_ensure_local,
        mock_ensure_venv,
        tmp_path,
        monkeypatch,
    ):
        """--skip-wizard --local-marketplace reinstall must build venv at LOCAL_CLONE_DIR too."""

        target_mp = tmp_path / "mp"
        target_mp.mkdir()
        target_local = tmp_path / "local-clone"
        target_local.mkdir()

        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target_mp)
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", target_local)
        mock_ensure_local.return_value = target_local
        mock_detect.return_value = InstallState(installed_plugins=["proj"])

        args = _make_args(reinstall=True, skip_wizard=True, local_marketplace=True)
        _reinstall(args)

        called_targets = {call.args[0] for call in mock_ensure_venv.call_args_list}
        assert target_mp in called_targets
        assert target_local in called_targets

    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.scan_stale_cache", side_effect=FileNotFoundError("skip"))
    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    @patch("installer.main.run_wizard")
    def test_wizard_path_passes_args(
        self,
        mock_wizard,
        mock_detect,
        _disp,
        _gip,
        _scan,
        _remove_mp,
        _add_mp,
        _install_plugin,
    ):
        """run_wizard must receive args=args so wizard's venv step sees --local-marketplace."""
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(reinstall=True, skip_wizard=False, local_marketplace=True)
        _reinstall(args)
        mock_wizard.assert_called_once()
        kwargs = mock_wizard.call_args.kwargs
        assert kwargs.get("args") is args

    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.main.install_plugin")
    @patch("installer.main.add_marketplace")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.scan_stale_cache", side_effect=FileNotFoundError("skip"))
    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    @patch("installer.main.run_wizard")
    def test_reinstall_skip_wizard_kills_before_ensure_shared_venv(
        self,
        _wizard,
        mock_detect,
        _disp,
        _gip,
        _scan,
        _remove_mp,
        _add_mp,
        _install_plugin,
        mock_ensure,
        tmp_path,
        monkeypatch,
    ):
        """--skip-wizard reinstall: prompt_kill_stale_sessions called before
        ensure_shared_venv."""
        from unittest.mock import MagicMock as _MagicMock

        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target)
        mock_detect.return_value = InstallState(installed_plugins=["proj"])

        parent = _MagicMock()
        parent.ensure_shared_venv = mock_ensure
        with patch(
            "installer.flow.kill_stale.prompt_kill_stale_sessions",
            parent.prompt_kill_stale_sessions,
        ):
            args = _make_args(reinstall=True, skip_wizard=True)
            _reinstall(args)
        names = [c[0] for c in parent.mock_calls]
        kill_idx = names.index("prompt_kill_stale_sessions")
        ensure_idx = names.index("ensure_shared_venv")
        assert kill_idx < ensure_idx, (
            f"prompt_kill_stale_sessions must precede ensure_shared_venv; got {names}"
        )


# ===================================================================
# _uninstall dispatch
# ===================================================================


class TestUninstall:
    """Tests for _uninstall()."""

    @patch("installer.main.get_installed_plugins", return_value=[])
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_no_installed_plugins(self, mock_detect, _disp, _gip):
        mock_detect.return_value = InstallState(installed_plugins=[])
        args = _make_args(uninstall=True)
        result = _uninstall(args)
        assert result == EXIT_SUCCESS

    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_uninstall_success(self, mock_detect, _disp, mock_remove_mp, _gip):
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(uninstall=True)
        result = _uninstall(args)
        assert result == EXIT_SUCCESS
        mock_remove_mp.assert_called_once()

    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.cleanup_config_files")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_uninstall_with_full_cleanup(
        self, mock_detect, _disp, mock_remove_mp, mock_cleanup, _gip
    ):
        """--full-cleanup triggers config file removal after marketplace removal."""
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(uninstall=True, full_cleanup=True)
        result = _uninstall(args)
        assert result == EXIT_SUCCESS
        mock_remove_mp.assert_called_once()
        mock_cleanup.assert_called_once()

    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.cleanup_config_files")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_uninstall_without_full_cleanup(
        self, mock_detect, _disp, _remove_mp, mock_cleanup, _gip
    ):
        """Without --full-cleanup, config files are not removed."""
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(uninstall=True, full_cleanup=False)
        result = _uninstall(args)
        assert result == EXIT_SUCCESS
        mock_cleanup.assert_not_called()

    @patch("installer.main.get_installed_plugins", return_value=["proj"])
    @patch("installer.main.remove_marketplace", side_effect=InstallerError("fail"))
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_uninstall_failure(self, mock_detect, _disp, _remove_mp, _gip):
        mock_detect.return_value = InstallState(installed_plugins=["proj"])
        args = _make_args(uninstall=True)
        result = _uninstall(args)
        assert result == EXIT_ERROR

    @patch(
        "installer.main.get_installed_plugins",
        return_value=["proj", "hooks", "sandbox"],
    )
    @patch("installer.main.cleanup_config_files")
    @patch("installer.main.remove_marketplace")
    @patch("installer.main.display_detection")
    @patch("installer.main.detect_existing")
    def test_uninstall_multiple_plugins(
        self, mock_detect, _disp, mock_remove_mp, mock_cleanup, _gip
    ):
        """Multiple installed plugins are all uninstalled via single marketplace remove."""
        mock_detect.return_value = InstallState(
            installed_plugins=["proj", "hooks", "sandbox"]
        )
        args = _make_args(uninstall=True, full_cleanup=True)
        result = _uninstall(args)
        assert result == EXIT_SUCCESS
        mock_remove_mp.assert_called_once()  # single atomic operation, not per-plugin
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
    @patch("installer.main.run_installer_flow", return_value=EXIT_SUCCESS)
    @patch("installer.main.build_parser")
    def test_main_default_mode_uses_tui(
        self, mock_parser, mock_flow, _root, _prereq, _lock, _release
    ):
        """Default (no --no-tui) calls run_installer_flow."""
        args = _make_args(no_tui=False)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        result = main()
        assert result == EXIT_SUCCESS
        mock_flow.assert_called_once()
        call_args = mock_flow.call_args[0]
        assert call_args[0] == "install"
        assert call_args[1] is args

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
    @patch("installer.main.run_installer_flow", return_value=EXIT_SUCCESS)
    @patch("installer.main.build_parser")
    def test_main_tui_reinstall_mode(
        self, mock_parser, mock_flow, _root, _prereq, _lock, _release
    ):
        args = _make_args(no_tui=False, reinstall=True)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        main()
        call_args = mock_flow.call_args[0]
        assert call_args[0] == "reinstall"
        assert call_args[1] is args

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main.run_installer_flow", return_value=EXIT_SUCCESS)
    @patch("installer.main.build_parser")
    def test_main_tui_uninstall_mode(
        self, mock_parser, mock_flow, _root, _prereq, _lock, _release
    ):
        args = _make_args(no_tui=False, uninstall=True)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()
        main()
        call_args = mock_flow.call_args[0]
        assert call_args[0] == "uninstall"
        assert call_args[1] is args

    @patch("installer.main.release_lock")
    @patch("installer.main.acquire_lock")
    @patch("installer.main.check_prerequisites")
    @patch("installer.main.check_root")
    @patch("installer.main.run_installer_flow", return_value=EXIT_SUCCESS)
    @patch("installer.main.build_parser")
    def test_tui_install_path_calls_run_installer_flow(
        self,
        mock_parser,
        mock_flow,
        _root,
        _prereq,
        _lock,
        _release,
    ):
        """TUI install path delegates entirely to run_installer_flow.

        Orphan cleanup, execute_install_plan, and full_cleanup are all handled
        inside run_installer_flow — main.py no longer has a post-exit block.
        """
        args = _make_args(no_tui=False)
        mock_parser.return_value.parse_args.return_value = args
        _lock.return_value = MagicMock()

        result = main()

        assert result == EXIT_SUCCESS
        mock_flow.assert_called_once()
        call_args = mock_flow.call_args[0]
        assert call_args[0] == "install"
        assert call_args[1] is args


# ===================================================================
# app.py unit-testable helpers
# (TestInstallerAppHelpers deleted in P3 #672 — InstallerApp class removed.
#  Config-writing, detection-row building, and flow callbacks are now
#  handled by run_installer_flow in installer/flow/installer_flow.py.)
# ===================================================================
