"""Tests for installer.wizard — post-install setup wizard."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from installer.wizard import (
    _atomic_write,
    _setup_proj_yaml,
    _setup_worktree_yaml,
    _yaml_line,
    run_wizard,
)


class TestYamlLine:
    def test_string_value(self):
        assert _yaml_line("key", "value") == "key: value\n"

    def test_bool_true(self):
        assert _yaml_line("enabled", True) == "enabled: true\n"

    def test_bool_false(self):
        assert _yaml_line("enabled", False) == "enabled: false\n"


class TestAtomicWrite:
    def test_creates_file(self, tmp_path: Path):
        target = tmp_path / "test.yaml"
        _atomic_write(target, "hello")
        assert target.read_text() == "hello"

    def test_creates_parent_dirs(self, tmp_path: Path):
        target = tmp_path / "nested" / "dir" / "test.yaml"
        _atomic_write(target, "content")
        assert target.exists()

    def test_overwrites_existing(self, tmp_path: Path):
        target = tmp_path / "test.yaml"
        target.write_text("old")
        _atomic_write(target, "new")
        assert target.read_text() == "new"

    def test_no_partial_write_on_error(self, tmp_path: Path):
        """If os.replace fails, the original file is preserved."""
        target = tmp_path / "test.yaml"
        target.write_text("original")

        with (
            patch(
                "installer.wizard.Path.replace",
                side_effect=OSError("boom"),
            ),
            pytest.raises(OSError, match="boom"),
        ):
            _atomic_write(target, "new content")

        # Original content preserved
        assert target.read_text() == "original"


class TestSetupProjYaml:
    def test_creates_new_config(self, mock_home: Path):
        """Prompts all questions and writes proj.yaml."""
        with (
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=[
                    "~/projects/tracking",
                    "~/projects",
                ],
            ),
            patch("installer.wizard.Confirm.ask", side_effect=[True, False]),
        ):
            console = MagicMock()
            _setup_proj_yaml(console, [])

        proj_yaml = mock_home / ".claude" / "proj.yaml"
        assert proj_yaml.exists()
        content = proj_yaml.read_text()
        assert "version: 1" in content
        assert "tracking_dir:" in content
        assert "sandbox_integration: true" in content
        assert "zoxide_integration: false" in content

    def test_keeps_existing_config(self, mock_home: Path):
        """When user says keep, existing config is untouched."""
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text("original: content\n")

        with patch("installer.wizard.Confirm.ask", return_value=True):
            console = MagicMock()
            _setup_proj_yaml(console, [])

        assert proj_yaml.read_text() == "original: content\n"

    def test_overwrites_when_user_says_no_keep(self, mock_home: Path):
        """When user declines to keep, new config is written."""
        proj_yaml = mock_home / ".claude" / "proj.yaml"
        proj_yaml.write_text("old\n")

        with (
            patch("installer.wizard.Confirm.ask", side_effect=[False, True, False]),
            patch(
                "installer.wizard.Prompt.ask",
                side_effect=[
                    "~/custom/tracking",
                    "~/custom/projects",
                ],
            ),
        ):
            console = MagicMock()
            _setup_proj_yaml(console, [])

        content = proj_yaml.read_text()
        assert "tracking_dir: ~/custom/tracking" in content


class TestSetupWorktreeYaml:
    def test_creates_new_config(self, mock_home: Path):
        with patch("installer.wizard.Prompt.ask", return_value="~/worktrees"):
            console = MagicMock()
            _setup_worktree_yaml(console)

        wt_yaml = mock_home / ".claude" / "worktree.yaml"
        assert wt_yaml.exists()
        content = wt_yaml.read_text()
        assert "default_worktree_dir: ~/worktrees" in content

    def test_keeps_existing(self, mock_home: Path):
        wt_yaml = mock_home / ".claude" / "worktree.yaml"
        wt_yaml.write_text("existing\n")

        with patch("installer.wizard.Confirm.ask", return_value=True):
            console = MagicMock()
            _setup_worktree_yaml(console)

        assert wt_yaml.read_text() == "existing\n"


class TestRunWizard:
    def test_skip_wizard(self, capsys):
        """--skip-wizard produces skip message and no prompts."""
        run_wizard(["proj"], skip=True)
        # Should not raise or prompt

    def test_proj_triggers_proj_yaml_setup(self, mock_home: Path):
        with (
            patch("installer.wizard._setup_proj_yaml") as mock_proj,
            patch("installer.wizard._setup_worktree_yaml") as mock_wt,
        ):
            run_wizard(["proj", "sandbox"], skip=False)
            mock_proj.assert_called_once()
            mock_wt.assert_not_called()

    def test_worktree_triggers_worktree_yaml_setup(self, mock_home: Path):
        with (
            patch("installer.wizard._setup_proj_yaml") as mock_proj,
            patch("installer.wizard._setup_worktree_yaml") as mock_wt,
        ):
            run_wizard(["worktree"], skip=False)
            mock_proj.assert_not_called()
            mock_wt.assert_called_once()

    def test_all_plugins_triggers_both(self, mock_home: Path):
        with (
            patch("installer.wizard._setup_proj_yaml") as mock_proj,
            patch("installer.wizard._setup_worktree_yaml") as mock_wt,
        ):
            run_wizard(["proj", "worktree", "hooks"], skip=False)
            mock_proj.assert_called_once()
            mock_wt.assert_called_once()

    def test_empty_plugins_skips_all(self, mock_home: Path):
        with (
            patch("installer.wizard._setup_proj_yaml") as mock_proj,
            patch("installer.wizard._setup_worktree_yaml") as mock_wt,
        ):
            run_wizard([], skip=False)
            mock_proj.assert_not_called()
            mock_wt.assert_not_called()
