"""Tests for installer.cli — argument parsing."""

from __future__ import annotations

import pytest

from installer.cli import build_parser


class TestBuildParser:
    """Tests for build_parser()."""

    def test_default_flags(self):
        """No flags produces default namespace."""
        parser = build_parser()
        args = parser.parse_args([])
        assert args.reinstall is False
        assert args.uninstall is False
        assert args.full_cleanup is False
        assert args.plugins is None
        assert args.skip_wizard is False
        assert args.verbose is False
        assert args.local_marketplace is False

    def test_reinstall_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--reinstall"])
        assert args.reinstall is True

    def test_uninstall_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--uninstall"])
        assert args.uninstall is True

    def test_mutual_exclusion_reinstall_uninstall(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--reinstall", "--uninstall"])

    def test_full_cleanup_standalone(self):
        """--full-cleanup alone is valid (main.py implies --uninstall)."""
        parser = build_parser()
        args = parser.parse_args(["--full-cleanup"])
        assert args.full_cleanup is True
        assert args.uninstall is False  # main.py sets this later

    def test_plugins_single(self):
        parser = build_parser()
        args = parser.parse_args(["--plugins", "proj"])
        assert args.plugins == ["proj"]

    def test_plugins_multiple(self):
        parser = build_parser()
        args = parser.parse_args(["--plugins", "proj", "worktree", "router"])
        assert args.plugins == ["proj", "worktree", "router"]

    def test_skip_wizard(self):
        parser = build_parser()
        args = parser.parse_args(["--skip-wizard"])
        assert args.skip_wizard is True

    def test_verbose(self):
        parser = build_parser()
        args = parser.parse_args(["--verbose"])
        assert args.verbose is True

    def test_no_tui_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--no-tui"])
        assert args.no_tui is True

    def test_no_tui_default(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.no_tui is False

    def test_branch_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--branch", "dev"])
        assert args.branch == "dev"

    def test_branch_default_none(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.branch is None

    def test_full_cleanup_with_uninstall(self):
        """--full-cleanup and --uninstall can be combined."""
        parser = build_parser()
        args = parser.parse_args(["--uninstall", "--full-cleanup"])
        assert args.uninstall is True
        assert args.full_cleanup is True

    def test_version_exits(self):
        parser = build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--version"])
        assert exc_info.value.code == 0

    def test_local_marketplace_default_false(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.local_marketplace is False

    def test_local_marketplace_flag(self):
        parser = build_parser()
        args = parser.parse_args(["--local-marketplace"])
        assert args.local_marketplace is True

    def test_local_marketplace_with_branch(self):
        parser = build_parser()
        args = parser.parse_args(["--local-marketplace", "--branch", "dev"])
        assert args.local_marketplace is True
        assert args.branch == "dev"

    def test_local_marketplace_with_reinstall(self):
        parser = build_parser()
        args = parser.parse_args(["--reinstall", "--local-marketplace"])
        assert args.local_marketplace is True
        assert args.reinstall is True
