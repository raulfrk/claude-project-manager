# installer/tests/flow/test_installer_flow.py
from unittest.mock import MagicMock, patch

from rich.console import Console

from installer.flow.install_plan import (
    InstallPlan,
    InstallResult,
)
from installer.flow.installer_flow import run_installer_flow
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
            patch("installer.flow.installer_flow.execute_install_plan") as mock_exec,
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            code = run_installer_flow("update", _Args(), console)
        assert code == 0
        mock_exec.assert_not_called()
