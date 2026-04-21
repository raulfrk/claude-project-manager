# installer/tests/flow/test_installer_flow.py
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from rich.console import Console

from installer.flow.install_plan import (
    InstallPlan,
    InstallResult,
)
from installer.flow.installer_flow import (
    _compute_integration_diff,
    run_installer_flow,
)
from installer.flow.pre_install_phase import PreInstallResult


class _Args:
    branch = None


def _ok() -> InstallResult:
    return InstallResult(success_count=1, failure_count=0, failures=[])


# ── Reinstall ──────────────────────────────────────────────────────────────


class TestReinstall:
    def test_cancelled_pre_phase(self) -> None:
        with patch(
            "installer.flow.installer_flow.pre_install_phase",
            return_value=PreInstallResult(state=None, proceed=False, exit_code=0),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("reinstall", _Args(), console)
        assert code == 0

    def test_reinstall_builds_and_executes(self) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj"]),
                    proceed=True,
                    mode_options={"reset_configs": False},
                ),
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ) as mock_exec,
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("reinstall", _Args(), console)
        assert code == 0
        plan_arg = mock_exec.call_args.args[0]
        assert isinstance(plan_arg, InstallPlan)
        assert any(a.action == "reinstall" for a in plan_arg.actions)

    def test_reinstall_reset_configs_deletes_yamls(self, tmp_path) -> None:
        """reset_configs=True removes ~/.claude/proj.yaml + worktree.yaml."""
        home = tmp_path / "home"
        claude = home / ".claude"
        claude.mkdir(parents=True)
        (claude / "proj.yaml").write_text("tracking_dir: /tmp/foo\n")
        (claude / "worktree.yaml").write_text("default_branch: main\n")
        # unrelated file survives
        (claude / "todoist.yaml").write_text("api_token: keep-me\n")

        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj"]),
                    proceed=True,
                    mode_options={"reset_configs": True},
                ),
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ),
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
            patch("installer.flow.installer_flow.Path.home", return_value=home),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("reinstall", _Args(), console)

        assert code == 0
        assert not (claude / "proj.yaml").exists()
        assert not (claude / "worktree.yaml").exists()
        assert (claude / "todoist.yaml").exists()

    def test_reinstall_reset_configs_false_keeps_yamls(self, tmp_path) -> None:
        """reset_configs=False leaves yamls untouched."""
        home = tmp_path / "home"
        claude = home / ".claude"
        claude.mkdir(parents=True)
        (claude / "proj.yaml").write_text("tracking_dir: /tmp/foo\n")
        (claude / "worktree.yaml").write_text("default_branch: main\n")

        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj"]),
                    proceed=True,
                    mode_options={"reset_configs": False},
                ),
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ),
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
            patch("installer.flow.installer_flow.Path.home", return_value=home),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("reinstall", _Args(), console)

        assert code == 0
        assert (claude / "proj.yaml").exists()
        assert (claude / "worktree.yaml").exists()

    def test_reinstall_calls_ensure_managed_section(self) -> None:
        """_run_reinstall must refresh managed CLAUDE.md before executing reinstall."""
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj"]),
                    proceed=True,
                    mode_options={"reset_configs": False},
                ),
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ),
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
            patch("installer.flow.installer_flow.ensure_managed_section") as mock_ems,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("reinstall", _Args(), console)
        assert code == 0
        mock_ems.assert_called_once_with(Path.home() / ".claude" / "CLAUDE.md")


# ── Uninstall ──────────────────────────────────────────────────────────────


class TestUninstall:
    def test_uninstall_with_full_cleanup(self) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj", "worktree"]),
                    proceed=True,
                    mode_options={"full_cleanup": True},
                ),
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=[
                    "proj@claude-project-manager",
                    "worktree@claude-project-manager",
                ],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=[
                    "proj@claude-project-manager",
                    "worktree@claude-project-manager",
                ],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ) as mock_exec,
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
            patch("installer.flow.installer_flow.remove_managed_section") as mock_rm,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("uninstall", _Args(), console)
        assert code == 0
        plan_arg = mock_exec.call_args.args[0]
        assert all(a.action == "uninstall" for a in plan_arg.actions)
        mock_rm.assert_called_once()

    def test_uninstall_no_installed_plugins(self) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=[]),
                    proceed=True,
                    mode_options={"full_cleanup": False},
                ),
            ),
            patch("installer.flow.installer_flow.execute_install_plan") as mock_exec,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("uninstall", _Args(), console)
        assert code == 0
        mock_exec.assert_not_called()


# ── Install ────────────────────────────────────────────────────────────────


class TestInstall:
    def test_install_selects_plugins_and_executes(self) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[MagicMock(name="proj")],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[("proj", "install")],
            ),
            patch(
                "installer.flow.installer_flow.run_wizard",
                return_value={"tracking_dir": "/tmp/tracking"},
            ),
            patch("installer.flow.installer_flow._write_wizard_result"),
            patch(
                "installer.flow.installer_flow.compute_hooks_diff",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.review_hooks_diff",
                return_value={"apply": set(), "remove": set()},
            ),
            patch("installer.flow.installer_flow.ensure_managed_section") as mock_ems,
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ) as mock_exec,
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("install", _Args(), console)
        assert code == 0
        plan = mock_exec.call_args.args[0]
        assert any(
            a.plugin_id == "proj@claude-project-manager" and a.action == "install"
            for a in plan.actions
        )
        mock_ems.assert_called_once_with(Path.home() / ".claude" / "CLAUDE.md")

    def test_install_cancelled_at_plugin_select(self) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[MagicMock(name="proj")],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[],
            ),
            patch("installer.flow.installer_flow.execute_install_plan") as mock_exec,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("install", _Args(), console)
        assert code == 0
        mock_exec.assert_not_called()

    def test_install_cancelled_at_hooks_diff(self) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[MagicMock(name="proj")],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[("proj", "install")],
            ),
            patch(
                "installer.flow.installer_flow.run_wizard",
                return_value={"tracking_dir": "/tmp/tracking"},
            ),
            patch("installer.flow.installer_flow._write_wizard_result"),
            patch(
                "installer.flow.installer_flow.compute_hooks_diff",
                return_value=[MagicMock()],  # non-empty, so hooks review fires
            ),
            patch(
                "installer.flow.installer_flow.review_hooks_diff",
                return_value=None,  # user cancelled
            ),
            patch("installer.flow.installer_flow.execute_install_plan") as mock_exec,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("install", _Args(), console)
        assert code == 0
        mock_exec.assert_not_called()

    def test_install_cancel_at_wizard(self) -> None:
        """Wizard returns None → exit 0, no further calls (no hooks diff, no exec)."""
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[MagicMock(name="proj")],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[("proj", "install")],
            ),
            patch(
                "installer.flow.installer_flow.run_wizard",
                return_value=None,  # user cancelled
            ),
            patch(
                "installer.flow.installer_flow.compute_hooks_diff",
            ) as mock_hooks,
            patch("installer.flow.installer_flow.execute_install_plan") as mock_exec,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("install", _Args(), console)
        assert code == 0
        mock_hooks.assert_not_called()
        mock_exec.assert_not_called()

    def test_install_cancel_at_integration_config(self) -> None:
        """configure_todoist returns None → exit 0, hooks diff + exec not called."""
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[MagicMock(name="todoist")],
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[("todoist", "install")],
            ),
            patch(
                "installer.flow.installer_flow.run_wizard",
                return_value={"tracking_dir": "/tmp/tracking"},
            ),
            patch("installer.flow.installer_flow._write_wizard_result"),
            patch(
                "installer.flow.installer_flow.configure_todoist",
                return_value=None,  # user cancelled
            ),
            patch(
                "installer.flow.installer_flow.compute_hooks_diff",
            ) as mock_hooks,
            patch("installer.flow.installer_flow.execute_install_plan") as mock_exec,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("install", _Args(), console)
        assert code == 0
        mock_hooks.assert_not_called()
        mock_exec.assert_not_called()

    def test_install_skips_wizard_when_no_proj_plugins(self) -> None:
        """Only 'worktree' selected → wizard NOT called (worktree is in _WIZARD_PLUGINS)."""
        # Use a plugin that is NOT in _WIZARD_PLUGINS, e.g. a hypothetical "sandbox"
        # Actually worktree IS in _WIZARD_PLUGINS per spec. Use a non-wizard plugin.
        # The only way to skip wizard is to have no _WIZARD_PLUGINS members selected.
        # Per spec, _WIZARD_PLUGINS = {"proj","router","todoist","trello","jira","worktree"}.
        # So we use a plugin name outside that set (e.g. "perms").
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[MagicMock(name="perms")],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[("perms", "install")],
            ),
            patch(
                "installer.flow.installer_flow.run_wizard",
            ) as mock_wizard,
            patch(
                "installer.flow.installer_flow.compute_hooks_diff",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.review_hooks_diff",
                return_value={"apply": set(), "remove": set()},
            ),
            patch("installer.flow.installer_flow.ensure_managed_section"),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["perms@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ),
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("install", _Args(), console)
        assert code == 0
        mock_wizard.assert_not_called()

    def test_install_cancel_at_trello_config(self) -> None:
        """configure_trello returns None → exit 0, skip hooks_diff + execute."""
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[MagicMock(name="trello")],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[("trello", "install")],
            ),
            patch(
                "installer.flow.installer_flow.run_wizard",
                return_value={"tracking_dir": "/tmp"},
            ),
            patch("installer.flow.installer_flow._write_wizard_result"),
            patch(
                "installer.flow.installer_flow.configure_trello",
                return_value=None,  # user cancelled
            ),
            patch("installer.flow.installer_flow.execute_install_plan") as mock_exec,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("install", _Args(), console)
        assert code == 0
        mock_exec.assert_not_called()

    def test_install_cancel_at_jira_config(self) -> None:
        """configure_jira returns None → exit 0, skip hooks_diff + execute."""
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[MagicMock(name="jira")],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[("jira", "install")],
            ),
            patch(
                "installer.flow.installer_flow.run_wizard",
                return_value={"tracking_dir": "/tmp"},
            ),
            patch("installer.flow.installer_flow._write_wizard_result"),
            patch(
                "installer.flow.installer_flow.configure_jira",
                return_value=None,
            ),
            patch("installer.flow.installer_flow.execute_install_plan") as mock_exec,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("install", _Args(), console)
        assert code == 0
        mock_exec.assert_not_called()

    def test_install_resolves_plugin_dirs_for_hooks_diff(self) -> None:
        """_run_install must pass non-empty plugin_dirs to compute_hooks_diff.

        Regression guard for the empty-list bug: when plugin_dirs=[] was passed,
        merge_defaults returned {} and the diff treated every hook as "to remove".
        Now _resolve_plugin_dirs is called with the selected plugin names so that
        each plugin's default-hooks.yaml is read correctly.
        """
        from pathlib import Path

        fake_dir = Path("/fake/cache/proj/1.0.0")

        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[MagicMock(name="proj")],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[("proj", "install")],
            ),
            patch(
                "installer.flow.installer_flow.run_wizard",
                return_value={"tracking_dir": "/tmp/tracking"},
            ),
            patch("installer.flow.installer_flow._write_wizard_result"),
            # _resolve_plugin_dirs returns one resolved dir for "proj"
            patch(
                "installer.flow.installer_flow._resolve_plugin_dirs",
                return_value=[fake_dir],
            ) as mock_resolve,
            patch(
                "installer.flow.installer_flow.compute_hooks_diff",
                return_value=[],
            ) as mock_hooks,
            patch(
                "installer.flow.installer_flow.review_hooks_diff",
                return_value={"apply": set(), "remove": set()},
            ),
            patch("installer.flow.installer_flow.ensure_managed_section"),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ),
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("install", _Args(), console)

        assert code == 0
        # _resolve_plugin_dirs must be called with the selected plugin names
        mock_resolve.assert_called_once_with(["proj"])
        # compute_hooks_diff must receive the resolved dirs, not []
        _hooks_call_args = mock_hooks.call_args
        passed_plugin_dirs = _hooks_call_args.args[1]
        assert passed_plugin_dirs == [fake_dir], (
            f"Expected plugin_dirs=[{fake_dir}] but got {passed_plugin_dirs!r} — "
            "passing [] breaks hooks diff (merge_defaults returns empty dict)"
        )


# ── Update ─────────────────────────────────────────────────────────────────


class TestUpdate:
    def test_update_selects_and_executes(self) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj"]),
                    proceed=True,
                ),
            ),
            patch(
                "installer.flow.installer_flow.compare_versions",
                return_value={"proj": ("1.0.0", "1.1.0")},
            ),
            patch(
                "installer.flow.installer_flow.select_updates",
                return_value=["proj"],
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ) as mock_exec,
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("update", _Args(), console)
        assert code == 0
        plan = mock_exec.call_args.args[0]
        assert any(
            a.plugin_id == "proj@claude-project-manager" and a.action == "update"
            for a in plan.actions
        )

    def test_update_no_diffs_returns_zero(self) -> None:
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj"]),
                    proceed=True,
                ),
            ),
            patch(
                "installer.flow.installer_flow.compare_versions",
                return_value={},
            ),
            patch("installer.flow.installer_flow.execute_install_plan"),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("update", _Args(), console)
        assert code == 0

    def test_update_calls_ensure_managed_section(self) -> None:
        """_run_update must refresh managed CLAUDE.md before executing updates."""
        with (
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(
                    state=MagicMock(installed_plugins=["proj"]),
                    proceed=True,
                ),
            ),
            patch(
                "installer.flow.installer_flow.compare_versions",
                return_value={"proj": ("1.0.0", "1.1.0")},
            ),
            patch(
                "installer.flow.installer_flow.select_updates",
                return_value=["proj"],
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["proj@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ),
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
            patch("installer.flow.installer_flow.ensure_managed_section") as mock_ems,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("update", _Args(), console)
        assert code == 0
        mock_ems.assert_called_once_with(Path.home() / ".claude" / "CLAUDE.md")


# ── Integration config diff gate (todo 682) ────────────────────────────────


class TestIntegrationConfigDiff:
    """Parity: configure_* results must pass through review_config_diff when
    existing config differs from proposed. Mirrors pre-P3 ConfigDiffScreen."""

    def _existing_home(self, tmp_path: Path) -> Path:
        home = tmp_path / "home"
        (home / ".claude").mkdir(parents=True)
        return home

    def test_compute_diff_first_time_skips(self, tmp_path: Path) -> None:
        home = self._existing_home(tmp_path)
        proposed = {"api_token": "abc", "sync_enabled": True, "auto_sync": True}
        with patch("installer.flow.installer_flow.Path.home", return_value=home):
            diff_text, is_first_time = _compute_integration_diff("todoist", proposed)
        assert is_first_time is True
        # Diff text may be non-empty (new values), but the call-site short-circuits
        # on is_first_time=True so content doesn't matter.

    def test_compute_diff_no_changes_returns_empty(self, tmp_path: Path) -> None:
        home = self._existing_home(tmp_path)
        (home / ".claude" / "todoist.yaml").write_text("api_token: abc\n")
        (home / ".claude" / "proj.yaml").write_text(
            yaml.safe_dump({"sync": {"todoist": {"enabled": True, "auto_sync": True}}})
        )
        proposed = {"api_token": "abc", "sync_enabled": True, "auto_sync": True}
        with patch("installer.flow.installer_flow.Path.home", return_value=home):
            diff_text, is_first_time = _compute_integration_diff("todoist", proposed)
        assert is_first_time is False
        assert not diff_text.strip()

    def test_compute_diff_shows_changes(self, tmp_path: Path) -> None:
        home = self._existing_home(tmp_path)
        (home / ".claude" / "todoist.yaml").write_text("api_token: OLD_TOKEN\n")
        (home / ".claude" / "proj.yaml").write_text(
            yaml.safe_dump(
                {"sync": {"todoist": {"enabled": False, "auto_sync": False}}}
            )
        )
        proposed = {"api_token": "NEW_TOKEN", "sync_enabled": True, "auto_sync": True}
        with patch("installer.flow.installer_flow.Path.home", return_value=home):
            diff_text, is_first_time = _compute_integration_diff("todoist", proposed)
        assert is_first_time is False
        assert "OLD_TOKEN" in diff_text
        assert "NEW_TOKEN" in diff_text

    def test_install_flow_skips_write_on_cancel(self, tmp_path: Path) -> None:
        home = self._existing_home(tmp_path)
        # Pre-existing config — will trigger a diff prompt
        (home / ".claude" / "todoist.yaml").write_text("api_token: OLD\n")
        (home / ".claude" / "proj.yaml").write_text(
            yaml.safe_dump(
                {"sync": {"todoist": {"enabled": False, "auto_sync": False}}}
            )
        )

        with (
            patch("installer.flow.installer_flow.Path.home", return_value=home),
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[("todoist", "install")],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["todoist@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.configure_todoist",
                return_value={
                    "api_token": "NEW",
                    "sync_enabled": True,
                    "auto_sync": True,
                },
            ),
            patch(
                "installer.flow.installer_flow.run_wizard",
                return_value={},
            ),
            patch("installer.flow.installer_flow._write_wizard_result"),
            patch(
                "installer.flow.installer_flow.review_config_diff",
                return_value=False,  # user cancels
            ) as mock_review,
            patch(
                "installer.flow.installer_flow._write_integration_result"
            ) as mock_write,
            patch(
                "installer.flow.installer_flow.review_hooks_diff",
                return_value=None,
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ),
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
            patch("installer.flow.installer_flow.ensure_managed_section"),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            run_installer_flow("install", _Args(), console)

        mock_review.assert_called_once()
        mock_write.assert_not_called()

    def test_install_flow_writes_on_confirm(self, tmp_path: Path) -> None:
        home = self._existing_home(tmp_path)
        (home / ".claude" / "todoist.yaml").write_text("api_token: OLD\n")
        (home / ".claude" / "proj.yaml").write_text(
            yaml.safe_dump(
                {"sync": {"todoist": {"enabled": False, "auto_sync": False}}}
            )
        )

        with (
            patch("installer.flow.installer_flow.Path.home", return_value=home),
            patch(
                "installer.flow.installer_flow.pre_install_phase",
                return_value=PreInstallResult(state=None, proceed=True),
            ),
            patch(
                "installer.flow.installer_flow.check_marketplace_registered",
                return_value=True,
            ),
            patch(
                "installer.flow.installer_flow.build_plugin_status_list",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.select_plugin_actions",
                return_value=[("todoist", "install")],
            ),
            patch(
                "installer.flow.installer_flow.get_available_plugins",
                return_value=["todoist@claude-project-manager"],
            ),
            patch(
                "installer.flow.installer_flow.get_installed_plugins",
                return_value=[],
            ),
            patch(
                "installer.flow.installer_flow.configure_todoist",
                return_value={
                    "api_token": "NEW",
                    "sync_enabled": True,
                    "auto_sync": True,
                },
            ),
            patch(
                "installer.flow.installer_flow.run_wizard",
                return_value={},
            ),
            patch("installer.flow.installer_flow._write_wizard_result"),
            patch(
                "installer.flow.installer_flow.review_config_diff",
                return_value=True,  # user confirms
            ),
            patch(
                "installer.flow.installer_flow._write_integration_result"
            ) as mock_write,
            patch(
                "installer.flow.installer_flow.review_hooks_diff",
                return_value=None,
            ),
            patch(
                "installer.flow.installer_flow.execute_install_plan",
                return_value=_ok(),
            ),
            patch("installer.flow.installer_flow.cleanup_orphaned_plugin_caches"),
            patch("installer.flow.installer_flow.ensure_managed_section"),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            run_installer_flow("install", _Args(), console)

        mock_write.assert_called_once_with(
            "todoist",
            {"api_token": "NEW", "sync_enabled": True, "auto_sync": True},
        )
