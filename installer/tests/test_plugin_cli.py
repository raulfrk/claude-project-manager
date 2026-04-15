"""Tests for installer.plugin_cli — subprocess wrappers for claude plugin CLI."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from installer.errors import InstallerError
from installer.plugin_cli import (
    _MARKETPLACE_NAME,
    _MARKETPLACE_SOURCE,
    add_marketplace,
    check_marketplace_registered,
    format_output,
    get_available_plugins,
    get_installed_plugin_versions,
    get_installed_plugins,
    install_plugin,
    remove_marketplace,
    uninstall_plugin,
    update_plugin,
)

_PATCH_TARGET = "installer.plugin_cli.subprocess.run"


# ============================================================================
# check_marketplace_registered
# ============================================================================


class TestCheckMarketplaceRegistered:
    def test_returns_true_when_present(self):
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout=f"  ❯ {_MARKETPLACE_NAME}\n    Source: GitHub\n",
            stderr="",
        )
        with patch(_PATCH_TARGET, return_value=result):
            assert check_marketplace_registered() is True

    def test_returns_false_when_absent(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="  ❯ some-other-marketplace\n", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            assert check_marketplace_registered() is False

    def test_custom_name(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="  ❯ custom-mp\n", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            assert check_marketplace_registered("custom-mp") is True

    def test_nonzero_exit_raises(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="error"
        )
        with (
            patch(_PATCH_TARGET, return_value=result),
            pytest.raises(InstallerError, match="Command failed"),
        ):
            check_marketplace_registered()

    def test_timeout_raises(self):
        with (
            patch(
                _PATCH_TARGET,
                side_effect=subprocess.TimeoutExpired(cmd="x", timeout=60),
            ),
            pytest.raises(InstallerError, match="timed out"),
        ):
            check_marketplace_registered()


# ============================================================================
# add_marketplace
# ============================================================================


class TestAddMarketplace:
    def test_success(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result) as mock_run:
            add_marketplace()
            args = mock_run.call_args[0][0]
            assert args == [
                "claude",
                "plugin",
                "marketplace",
                "add",
                _MARKETPLACE_SOURCE,
            ]

    def test_custom_source(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result) as mock_run:
            add_marketplace("custom/source")
            args = mock_run.call_args[0][0]
            assert "custom/source" in args

    def test_branch_appends_ref(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result) as mock_run:
            add_marketplace(branch="dev")
            args = mock_run.call_args[0][0]
            assert f"{_MARKETPLACE_SOURCE}#dev" in args

    def test_branch_none_no_ref(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result) as mock_run:
            add_marketplace(branch=None)
            args = mock_run.call_args[0][0]
            assert _MARKETPLACE_SOURCE in args
            assert "#" not in args[-1]

    def test_failure_raises(self):
        result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="bad",
        )
        with (
            patch(_PATCH_TARGET, return_value=result),
            pytest.raises(InstallerError, match="Command failed"),
        ):
            add_marketplace()

    def test_timeout_raises(self):
        with (
            patch(
                _PATCH_TARGET,
                side_effect=subprocess.TimeoutExpired(cmd="x", timeout=60),
            ),
            pytest.raises(InstallerError, match="timed out"),
        ):
            add_marketplace()


# ============================================================================
# remove_marketplace
# ============================================================================


class TestRemoveMarketplace:
    def test_success(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result) as mock_run:
            remove_marketplace()
            args = mock_run.call_args[0][0]
            assert args == [
                "claude",
                "plugin",
                "marketplace",
                "remove",
                _MARKETPLACE_NAME,
            ]

    def test_failure_does_not_raise(self):
        """remove_marketplace uses check=False so it doesn't raise on failure."""
        result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="not found",
        )
        with patch(_PATCH_TARGET, return_value=result):
            remove_marketplace()  # should not raise


# ============================================================================
# get_installed_plugins
# ============================================================================


class TestGetInstalledPlugins:
    def test_parses_json_output(self):
        data = {
            "installed": [
                {"id": f"sandbox@{_MARKETPLACE_NAME}"},
                {"id": f"proj@{_MARKETPLACE_NAME}"},
                {"id": "other@different-marketplace"},
            ]
        }
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(data), stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            plugins = get_installed_plugins()
            assert plugins == [
                f"sandbox@{_MARKETPLACE_NAME}",
                f"proj@{_MARKETPLACE_NAME}",
            ]

    def test_empty_json(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"installed": []}), stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            assert get_installed_plugins() == []

    def test_invalid_json_returns_empty(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not json", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            assert get_installed_plugins() == []

    def test_failure_raises(self):
        result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="err",
        )
        with patch(_PATCH_TARGET, return_value=result), pytest.raises(InstallerError):
            get_installed_plugins()


# ============================================================================
# get_available_plugins
# ============================================================================


class TestGetAvailablePlugins:
    def test_parses_json_output(self):
        data = {
            "available": [
                {"pluginId": f"hooks@{_MARKETPLACE_NAME}"},
                {"pluginId": f"proj@{_MARKETPLACE_NAME}"},
                {"pluginId": "other@different-marketplace"},
            ]
        }
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(data), stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            plugins = get_available_plugins()
            assert plugins == [
                f"hooks@{_MARKETPLACE_NAME}",
                f"proj@{_MARKETPLACE_NAME}",
            ]

    def test_empty_available(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"available": []}), stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            assert get_available_plugins() == []

    def test_invalid_json_returns_empty(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="bad", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            assert get_available_plugins() == []

    def test_uses_json_and_available_flags(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps({"available": []}), stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result) as mock_run:
            get_available_plugins()
            args = mock_run.call_args[0][0]
            assert "--available" in args
            assert "--json" in args


# ============================================================================
# install_plugin
# ============================================================================


class TestInstallPlugin:
    def test_success(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result) as mock_run:
            install_plugin(f"sandbox@{_MARKETPLACE_NAME}")
            args = mock_run.call_args[0][0]
            assert args == [
                "claude",
                "plugin",
                "install",
                f"sandbox@{_MARKETPLACE_NAME}",
            ]

    def test_failure_raises(self):
        result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="not found",
        )
        with (
            patch(_PATCH_TARGET, return_value=result),
            pytest.raises(InstallerError, match="Command failed"),
        ):
            install_plugin(f"sandbox@{_MARKETPLACE_NAME}")

    def test_timeout_raises(self):
        with (
            patch(
                _PATCH_TARGET,
                side_effect=subprocess.TimeoutExpired(cmd="x", timeout=60),
            ),
            pytest.raises(InstallerError, match="timed out"),
        ):
            install_plugin(f"sandbox@{_MARKETPLACE_NAME}")


# ============================================================================
# update_plugin
# ============================================================================


class TestUpdatePlugin:
    def test_success(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result) as mock_run:
            update_plugin(f"proj@{_MARKETPLACE_NAME}")
            args = mock_run.call_args[0][0]
            assert args == [
                "claude",
                "plugin",
                "update",
                f"proj@{_MARKETPLACE_NAME}",
            ]

    def test_failure_raises(self):
        result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="fail",
        )
        with patch(_PATCH_TARGET, return_value=result), pytest.raises(InstallerError):
            update_plugin(f"proj@{_MARKETPLACE_NAME}")

    def test_timeout_raises(self):
        with (
            patch(
                _PATCH_TARGET,
                side_effect=subprocess.TimeoutExpired(cmd="x", timeout=60),
            ),
            pytest.raises(InstallerError, match="timed out"),
        ):
            update_plugin(f"proj@{_MARKETPLACE_NAME}")


# ============================================================================
# uninstall_plugin
# ============================================================================


class TestUninstallPlugin:
    def test_success(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result) as mock_run:
            uninstall_plugin(f"sandbox@{_MARKETPLACE_NAME}")
            args = mock_run.call_args[0][0]
            assert args == [
                "claude",
                "plugin",
                "uninstall",
                f"sandbox@{_MARKETPLACE_NAME}",
            ]

    def test_failure_does_not_raise(self):
        """uninstall_plugin uses check=False so it doesn't raise on failure."""
        result = subprocess.CompletedProcess(
            args=[],
            returncode=1,
            stdout="",
            stderr="err",
        )
        with patch(_PATCH_TARGET, return_value=result):
            uninstall_plugin(f"sandbox@{_MARKETPLACE_NAME}")  # should not raise

    def test_timeout_raises(self):
        with (
            patch(
                _PATCH_TARGET,
                side_effect=subprocess.TimeoutExpired(cmd="x", timeout=60),
            ),
            pytest.raises(InstallerError, match="timed out"),
        ):
            uninstall_plugin(f"sandbox@{_MARKETPLACE_NAME}")


# ============================================================================
# format_output
# ============================================================================


class TestFormatOutput:
    def test_stdout_only(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="hello", stderr=""
        )
        assert format_output(result) == "hello"

    def test_stderr_only(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr="oops"
        )
        assert format_output(result) == "oops"

    def test_both_stdout_and_stderr(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="out", stderr="err"
        )
        assert format_output(result) == "out\nerr"

    def test_empty_output(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="", stderr=""
        )
        assert format_output(result) == "(no output)"


# ============================================================================
# get_installed_plugins — edge cases
# ============================================================================


class TestGetInstalledPluginsEdgeCases:
    def test_list_format_data(self):
        """When JSON data is a list instead of dict with 'installed' key."""
        data = [
            {"id": f"proj@{_MARKETPLACE_NAME}"},
            {"id": "other@different"},
        ]
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(data), stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            plugins = get_installed_plugins()
            assert plugins == [f"proj@{_MARKETPLACE_NAME}"]

    def test_missing_id_field_skipped(self):
        """Plugin entries without 'id' key are skipped."""
        data = {
            "installed": [
                {"name": "no-id-field"},
                {"id": f"proj@{_MARKETPLACE_NAME}"},
            ]
        }
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(data), stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            plugins = get_installed_plugins()
            assert plugins == [f"proj@{_MARKETPLACE_NAME}"]


# ============================================================================
# get_installed_plugin_versions
# ============================================================================


class TestGetInstalledPluginVersions:
    def test_parses_versions(self):
        data = {
            "installed": [
                {"id": f"proj@{_MARKETPLACE_NAME}", "version": "4.0.0"},
                {"id": f"router@{_MARKETPLACE_NAME}", "version": "2.2.0"},
                {"id": "other@different", "version": "1.0.0"},
            ]
        }
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(data), stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            versions = get_installed_plugin_versions()
            assert versions == {"proj": "4.0.0", "router": "2.2.0"}

    def test_missing_version_skipped(self):
        data = {
            "installed": [
                {"id": f"proj@{_MARKETPLACE_NAME}", "version": "4.0.0"},
                {"id": f"router@{_MARKETPLACE_NAME}"},
            ]
        }
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(data), stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            versions = get_installed_plugin_versions()
            assert versions == {"proj": "4.0.0"}

    def test_invalid_json_returns_empty(self):
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="not json", stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            assert get_installed_plugin_versions() == {}

    def test_list_format_data(self):
        data = [
            {"id": f"proj@{_MARKETPLACE_NAME}", "version": "3.0.0"},
            {"id": "other@different", "version": "1.0.0"},
        ]
        result = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(data), stderr=""
        )
        with patch(_PATCH_TARGET, return_value=result):
            versions = get_installed_plugin_versions()
            assert versions == {"proj": "3.0.0"}
