"""Tests for code quality fixes 475.34-475.40."""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import yaml

from server.lib.conditions import _load_proj_config
from server.lib.constants import DEFAULT_SERVER_PORTS
from server.lib.http_client import post_hook
from server.lib.models import Hook
from server.lib.storage import _validate_registry_dict, load

# ── 475.34: specific exceptions in storage.py I/O ───────────────────────────


class TestStorageSpecificExceptions:
    """475.34 — broad except replaced with FileNotFoundError/PermissionError/YAMLError."""

    def test_load_permission_error_returns_empty(self, tmp_path: Path, caplog):
        """PermissionError during open → empty registry + WARNING log."""
        p = tmp_path / "hooks.yaml"
        p.write_text(yaml.dump({"hooks": [], "servers": {}, "settings": {}}))
        p.chmod(0o000)
        try:
            with caplog.at_level(logging.WARNING):
                reg = load(p)
            assert reg.hooks == []
            assert "Cannot open" in caplog.text or "Permission" in caplog.text
        finally:
            p.chmod(0o644)

    def test_load_invalid_yaml_returns_empty(self, tmp_path: Path, caplog):
        """Malformed YAML → empty registry + WARNING log."""
        p = tmp_path / "hooks.yaml"
        p.write_text("{{{invalid yaml")
        with caplog.at_level(logging.WARNING):
            reg = load(p)
        assert reg.hooks == []
        assert "Invalid YAML" in caplog.text

    def test_load_failures_yaml_error_logs_warning(self, tmp_path: Path, caplog):
        """_load_failures with bad YAML logs specific warning."""
        from server.lib.storage import _load_failures

        p = tmp_path / "fail.yaml"
        p.write_text("{{{bad yaml")
        with caplog.at_level(logging.WARNING):
            result = _load_failures(p)
        assert result == []
        assert "Invalid YAML" in caplog.text


# ── 475.35: warn when proj.yaml missing ─────────────────────────────────────


class TestConditionsMissingProjYaml:
    """475.35 — logger.warning when proj.yaml not found."""

    def test_missing_proj_yaml_logs_warning(self, tmp_path: Path, caplog):
        nonexistent = tmp_path / "does-not-exist.yaml"
        with caplog.at_level(logging.WARNING):
            result = _load_proj_config(nonexistent)
        assert result == {}
        assert "proj.yaml not found" in caplog.text


# ── 475.36: JSON parse errors logged at WARNING ─────────────────────────────


class TestHttpClientJsonWarning:
    """475.36 — JSON parse errors logged at WARNING instead of DEBUG."""

    @pytest.mark.asyncio
    async def test_json_parse_failure_logs_warning(self, caplog):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "not json at all"
        mock_resp.json.side_effect = ValueError("No JSON")

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("server.lib.http_client.httpx.AsyncClient", return_value=mock_client),
            caplog.at_level(logging.WARNING),
        ):
            fr = await post_hook(
                hook_id="h1",
                url="http://localhost:9000/hook",
                target_tool="tool",
                params={},
            )
        assert fr.ok is False
        assert "Failed to parse hook response as JSON" in caplog.text


# ── 475.37: shared DEFAULT_SERVER_PORTS constant ────────────────────────────


class TestSharedPortConstant:
    """475.37 — fire.py and discovery.py both use constants.DEFAULT_SERVER_PORTS."""

    def test_fire_uses_shared_constant(self):
        from server.tools.fire import _DEFAULT_SERVER_PORTS

        assert _DEFAULT_SERVER_PORTS is DEFAULT_SERVER_PORTS

    def test_discovery_uses_shared_constant(self):
        from server.lib.discovery import _DEFAULT_SERVER_PORTS

        assert _DEFAULT_SERVER_PORTS is DEFAULT_SERVER_PORTS

    def test_constant_has_expected_keys(self):
        expected = {"hooks", "sandbox", "proj", "worktree", "trello", "jira", "todoist"}
        assert set(DEFAULT_SERVER_PORTS.keys()) == expected


# ── 475.38: validate socket path before connect ─────────────────────────────


class TestSocketValidation:
    """475.38 — glob socket candidate validated with stat.S_ISSOCK."""

    def test_non_socket_file_skipped(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, caplog):
        """Regular file matching glob pattern is skipped with warning."""
        from server.tools.fire import _resolve_server_url

        # Create a regular file that looks like a socket
        fake = tmp_path / "claude-cpm-proj-12345.sock"
        fake.write_text("not a socket")

        registry_dir = tmp_path / "sockets"
        registry_dir.mkdir()
        monkeypatch.setenv("HOOK_TRANSPORT", "unix")
        monkeypatch.setattr("server.tools.fire._SOCKET_REGISTRY_DIR", registry_dir)

        with (
            patch("server.tools.fire.glob.glob", return_value=[str(fake)]),
            patch("server.tools.fire.os.path.getmtime", return_value=1.0),
            caplog.at_level(logging.WARNING),
        ):
            result = _resolve_server_url("proj", 19102)

        # Falls through to last-resort (server name as-is)
        assert result == "proj"
        assert "not a socket" in caplog.text

    def test_actual_socket_accepted(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        """A real socket file is accepted."""
        import socket

        from server.tools.fire import _resolve_server_url

        sock_path = tmp_path / "test.sock"
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.bind(str(sock_path))

            registry_dir = tmp_path / "sockets"
            registry_dir.mkdir()
            monkeypatch.setenv("HOOK_TRANSPORT", "unix")
            monkeypatch.setattr("server.tools.fire._SOCKET_REGISTRY_DIR", registry_dir)

            with (
                patch("server.tools.fire.glob.glob", return_value=[str(sock_path)]),
                patch("server.tools.fire.os.path.getmtime", return_value=1.0),
            ):
                result = _resolve_server_url("proj", 19102)

            assert result == f"unix://{sock_path}"
        finally:
            s.close()


# ── 475.39: exception context in nonblocking dispatch ────────────────────────


class TestNonblockingExceptionContext:
    """475.39 — _launch_nonblocking uses exc_info=True in logger.warning."""

    @pytest.mark.asyncio
    async def test_nonblocking_exception_logged_with_context(self, tmp_path: Path, caplog):
        from server.tools.fire import _launch_nonblocking

        hook = Hook(
            id="h-test",
            trigger_tool="trig",
            target_tool="tgt",
            server="srv",
            param_mapping={},
        )
        source = {"key": "val"}

        with (
            patch("server.tools.fire._fire_single", side_effect=RuntimeError("boom")),
            patch("server.tools.fire.storage") as mock_storage,
            caplog.at_level(logging.WARNING),
        ):
            await _launch_nonblocking(hook, source, "{}")

        assert "Non-blocking hook h-test failed unexpectedly" in caplog.text
        # exc_info=True means the traceback is included
        assert "RuntimeError" in caplog.text
        mock_storage.log_failure.assert_called_once()


# ── 475.40: YAML schema validation for hooks.yaml ───────────────────────────


class TestRegistryValidation:
    """475.40 — _validate_registry_dict checks for expected keys."""

    def test_valid_dict_with_hooks_key(self):
        assert _validate_registry_dict({"hooks": []}) is True

    def test_valid_dict_with_servers_key(self):
        assert _validate_registry_dict({"servers": {}}) is True

    def test_valid_dict_with_settings_key(self):
        assert _validate_registry_dict({"settings": {}}) is True

    def test_valid_dict_with_all_keys(self):
        assert _validate_registry_dict({"hooks": [], "servers": {}, "settings": {}}) is True

    def test_invalid_dict_unknown_keys_only(self):
        assert _validate_registry_dict({"random": "stuff"}) is False

    def test_invalid_non_dict(self):
        assert _validate_registry_dict([1, 2, 3]) is False
        assert _validate_registry_dict("string") is False
        assert _validate_registry_dict(None) is False

    def test_load_returns_empty_on_invalid_schema(self, tmp_path: Path, caplog):
        p = tmp_path / "hooks.yaml"
        p.write_text(yaml.dump({"random_key": "no hooks here"}))
        with caplog.at_level(logging.WARNING):
            reg = load(p)
        assert reg.hooks == []
        assert "Invalid hooks.yaml schema" in caplog.text
