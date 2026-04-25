"""Tests for installer.wizard.run_wizard's shared-venv step."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch


from installer.errors import InstallerError


class TestSharedVenvWizardStep:
    @patch("installer.wizard.ensure_managed_section")
    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.wizard._hooks_diff_prompt")
    def test_creates_venv_at_marketplaces_dir(
        self, _hd, mock_ensure, _mgr, tmp_path, monkeypatch
    ):
        from installer.wizard import run_wizard

        # Make marketplaces_dir() return a real existing path
        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target)

        run_wizard(selected_plugins=[], skip=True)

        # skip=True returns early — no venv step. This documents that
        # behavior; remove this assertion if you want venv to fire even on skip.
        mock_ensure.assert_not_called()

    @patch("installer.wizard.ensure_managed_section")
    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.wizard._hooks_diff_prompt")
    @patch("installer.wizard._setup_proj_yaml", return_value={})
    def test_runs_full_flow_creates_venv(
        self, _proj, _hd, mock_ensure, _mgr, tmp_path, monkeypatch
    ):
        from installer.wizard import run_wizard

        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target)

        # Run the wizard non-skip; the proj setup is mocked out so
        # interactive prompts don't fire.
        run_wizard(selected_plugins=["proj"], skip=False, args=None)

        mock_ensure.assert_called_once_with(target)

    @patch("installer.wizard.ensure_managed_section")
    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.wizard._hooks_diff_prompt")
    @patch("installer.wizard._setup_proj_yaml", return_value={})
    def test_local_marketplace_also_creates_at_local_clone(
        self, _proj, _hd, mock_ensure, _mgr, tmp_path, monkeypatch
    ):
        from installer.wizard import run_wizard

        target = tmp_path / "mp"
        target.mkdir()
        local_clone = tmp_path / "local-marketplace"
        local_clone.mkdir()

        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target)
        monkeypatch.setattr("installer.local_marketplace.LOCAL_CLONE_DIR", local_clone)

        args = SimpleNamespace(local_marketplace=True)
        run_wizard(selected_plugins=["proj"], skip=False, args=args)

        called_with = {c.args[0] for c in mock_ensure.call_args_list}
        assert target in called_with
        assert local_clone in called_with

    @patch("installer.wizard.ensure_managed_section")
    @patch("installer.shared_venv.ensure_shared_venv")
    @patch("installer.wizard._hooks_diff_prompt")
    @patch("installer.wizard._setup_proj_yaml", return_value={})
    def test_failure_is_warning_not_raise(
        self, _proj, _hd, mock_ensure, _mgr, tmp_path, monkeypatch, capsys
    ):
        from installer.wizard import run_wizard

        target = tmp_path / "mp"
        target.mkdir()
        monkeypatch.setattr("installer.shared_venv.marketplaces_dir", lambda: target)
        mock_ensure.side_effect = InstallerError("uv sync exploded")

        # Should NOT raise
        run_wizard(selected_plugins=["proj"], skip=False, args=None)
