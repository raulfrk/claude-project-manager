# installer/tests/flow/test_pre_install_phase.py
from pathlib import Path
from unittest.mock import MagicMock, patch

from rich.console import Console

from installer.flow.confirm import ConfirmResult
from installer.flow.pre_install_phase import (
    PreInstallResult,
    pre_install_phase,
)


class _Args:
    branch = None


class TestPreInstallPhaseInstall:
    def test_install_no_detection(self) -> None:
        console = Console(width=80, force_terminal=False, no_color=True)
        result = pre_install_phase("install", _Args(), console)
        assert isinstance(result, PreInstallResult)
        assert result.proceed is True
        assert result.state is None


class TestPreInstallPhaseUpdate:
    def test_update_cancel_at_detection(self) -> None:
        with (
            patch(
                "installer.flow.pre_install_phase.detect_existing",
                return_value=MagicMock(installed_plugins=["proj"]),
            ),
            patch(
                "installer.flow.pre_install_phase.show_detection_and_confirm",
                return_value=False,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("update", _Args(), console)
        assert result.proceed is False

    def test_update_proceeds(self) -> None:
        with (
            patch(
                "installer.flow.pre_install_phase.detect_existing",
                return_value=MagicMock(installed_plugins=["proj"]),
            ),
            patch(
                "installer.flow.pre_install_phase.show_detection_and_confirm",
                return_value=True,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("update", _Args(), console)
        assert result.proceed is True


class TestPreInstallPhaseReinstall:
    def test_cancel_at_detection(self) -> None:
        with (
            patch(
                "installer.flow.pre_install_phase.detect_existing",
                return_value=MagicMock(installed_plugins=["proj"]),
            ),
            patch(
                "installer.flow.pre_install_phase.show_detection_and_confirm",
                return_value=False,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("reinstall", _Args(), console)
        assert result.proceed is False

    def test_cancel_at_reinstall_confirm(self) -> None:
        with (
            patch(
                "installer.flow.pre_install_phase.detect_existing",
                return_value=MagicMock(installed_plugins=["proj"]),
            ),
            patch(
                "installer.flow.pre_install_phase.show_detection_and_confirm",
                return_value=True,
            ),
            patch(
                "installer.flow.pre_install_phase.confirm_with_options",
                return_value=ConfirmResult(confirmed=False, options={}),
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("reinstall", _Args(), console)
        assert result.proceed is False

    def test_reinstall_no_orphans(self) -> None:
        with (
            patch(
                "installer.flow.pre_install_phase.detect_existing",
                return_value=MagicMock(installed_plugins=["proj"]),
            ),
            patch(
                "installer.flow.pre_install_phase.show_detection_and_confirm",
                return_value=True,
            ),
            patch(
                "installer.flow.pre_install_phase.confirm_with_options",
                return_value=ConfirmResult(
                    confirmed=True, options={"reset_configs": False}
                ),
            ),
            patch(
                "installer.flow.pre_install_phase.scan_stale_cache",
                return_value=MagicMock(orphans=[]),
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("reinstall", _Args(), console)
        assert result.proceed is True
        assert result.mode_options == {"reset_configs": False}
        assert result.orphans_to_remove == []

    def test_reinstall_with_orphans_accepted(self, tmp_path) -> None:
        call_idx = {"n": 0}

        # Create real paths so the is_dir/is_file guards pass in CI.
        fake_cache = tmp_path / "cache"
        fake_cache.mkdir()
        fake_marketplace = tmp_path / "marketplace.json"
        fake_marketplace.write_text("{}")

        def confirm_side_effect(*a, **k):
            call_idx["n"] += 1
            if call_idx["n"] == 1:
                # Main reinstall confirm
                return ConfirmResult(confirmed=True, options={"reset_configs": True})
            # Orphan confirm
            return ConfirmResult(confirmed=True, options={})

        with (
            patch(
                "installer.flow.pre_install_phase.detect_existing",
                return_value=MagicMock(installed_plugins=["proj"]),
            ),
            patch(
                "installer.flow.pre_install_phase.show_detection_and_confirm",
                return_value=True,
            ),
            patch(
                "installer.flow.pre_install_phase.confirm_with_options",
                side_effect=confirm_side_effect,
            ),
            patch(
                "installer.flow.pre_install_phase.scan_stale_cache",
                return_value=MagicMock(orphans=["stale-plugin"]),
            ),
            patch(
                "installer.flow.pre_install_phase._cache_dir",
                return_value=fake_cache,
            ),
            patch(
                "installer.flow.pre_install_phase._marketplace_path",
                return_value=fake_marketplace,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("reinstall", _Args(), console)
        assert result.proceed is True
        assert result.mode_options == {"reset_configs": True}
        assert result.orphans_to_remove == ["stale-plugin"]


class TestPreInstallPhaseUninstall:
    def test_cancel(self) -> None:
        with (
            patch(
                "installer.flow.pre_install_phase.detect_existing",
                return_value=MagicMock(installed_plugins=["proj"]),
            ),
            patch(
                "installer.flow.pre_install_phase.show_detection_and_confirm",
                return_value=True,
            ),
            patch(
                "installer.flow.pre_install_phase.confirm_with_options",
                return_value=ConfirmResult(confirmed=False, options={}),
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("uninstall", _Args(), console)
        assert result.proceed is False

    def test_uninstall_full_cleanup(self) -> None:
        with (
            patch(
                "installer.flow.pre_install_phase.detect_existing",
                return_value=MagicMock(installed_plugins=["proj"]),
            ),
            patch(
                "installer.flow.pre_install_phase.show_detection_and_confirm",
                return_value=True,
            ),
            patch(
                "installer.flow.pre_install_phase.confirm_with_options",
                return_value=ConfirmResult(
                    confirmed=True, options={"full_cleanup": True}
                ),
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("uninstall", _Args(), console)
        assert result.proceed is True
        assert result.mode_options == {"full_cleanup": True}


class TestPreInstallPhaseUnknown:
    def test_unknown_mode(self) -> None:
        console = Console(width=80, force_terminal=False, no_color=True)
        result = pre_install_phase("unknown_mode", _Args(), console)
        assert result.proceed is False
        assert result.exit_code == 2


class TestPreInstallPhaseCorruptYaml:
    def test_corrupt_yaml_cancel_aborts(self) -> None:
        from installer._config_loader import ConfigLoadError

        error = ValueError("yaml parse error")

        def mock_load_yaml(path: Path):
            if "proj" in path.name:
                raise ConfigLoadError(path, error)
            return {}

        with (
            patch(
                "installer.flow.pre_install_phase.load_existing_yaml",
                side_effect=mock_load_yaml,
            ),
            patch(
                "installer.flow.pre_install_phase.show_corrupt_yaml_and_confirm",
                return_value=False,
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("install", _Args(), console)
        assert result.proceed is False

    def test_corrupt_yaml_continue_proceeds(self) -> None:
        from installer._config_loader import ConfigLoadError

        error = ValueError("yaml parse error")

        def mock_load_yaml(path: Path):
            if "proj" in path.name:
                raise ConfigLoadError(path, error)
            return {}

        with (
            patch(
                "installer.flow.pre_install_phase.load_existing_yaml",
                side_effect=mock_load_yaml,
            ),
            patch(
                "installer.flow.pre_install_phase.show_corrupt_yaml_and_confirm",
                return_value=True,
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("install", _Args(), console)
        assert result.proceed is True

    def test_valid_yaml_no_prompt(self) -> None:
        prompt_called = {"n": 0}

        def _not_called(*a, **k):
            prompt_called["n"] += 1
            return True

        with (
            patch(
                "installer.flow.pre_install_phase.load_existing_yaml",
                return_value={},
            ),
            patch(
                "installer.flow.pre_install_phase.show_corrupt_yaml_and_confirm",
                side_effect=_not_called,
            ),
            patch.object(Path, "exists", return_value=True),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = pre_install_phase("install", _Args(), console)
        assert prompt_called["n"] == 0
        assert result.proceed is True
