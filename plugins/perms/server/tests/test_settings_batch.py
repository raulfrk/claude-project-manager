"""Tests for batch_setup and batch_revoke in server.tools.settings."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from server.lib import storage
from server.tools.settings import batch_revoke, batch_setup


def _write_settings(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


def _read_settings(path: Path) -> dict[str, object]:
    return json.loads(path.read_text())  # type: ignore[return-value]


def _read_allow(path: Path) -> list[str]:
    data = _read_settings(path)
    perms = data.get("permissions", {})
    assert isinstance(perms, dict)
    allow = perms.get("allow", [])
    assert isinstance(allow, list)
    return allow  # type: ignore[return-value]


def _read_sandbox_allow_write(path: Path) -> list[str]:
    data = _read_settings(path)
    sandbox = data.get("sandbox", {})
    assert isinstance(sandbox, dict)
    fs = sandbox.get("filesystem", {})
    assert isinstance(fs, dict)
    return fs.get("allowWrite", [])  # type: ignore[return-value]


def _write_local_settings(path: Path, data: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def user_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / ".claude" / "settings.json"
    monkeypatch.setattr(storage, "_USER_SETTINGS", path)
    return path


@pytest.fixture()
def sandbox_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Return path to ~/.claude/settings.local.json with sandbox.enabled=true."""
    local_path = tmp_path / ".claude" / "settings.local.json"
    _write_local_settings(local_path, {"sandbox": {"enabled": True}})
    monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", local_path)
    monkeypatch.setattr(storage, "_USER_SETTINGS", tmp_path / ".claude" / "settings.json")
    return local_path


# ---------------------------------------------------------------------------
# TestBatchSetup — sandbox mode (paths + MCP rules)
# ---------------------------------------------------------------------------


class TestBatchSetup:
    def test_adds_paths_and_mcp_rules(self, sandbox_settings: Path) -> None:
        result = batch_setup(
            paths=["/home/user/proj", "/home/user/other"],
            mcp_servers=["proj", "perms"],
            scope="user",
            target="sandbox",
        )
        assert "Updated" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/proj" in aw
        assert "/home/user/other" in aw
        allow = _read_allow(sandbox_settings)
        assert "mcp__proj__*" in allow
        assert "mcp__perms__*" in allow

    def test_single_write(self, sandbox_settings: Path) -> None:
        """After batch_setup, file exists and contains both sandbox paths and MCP rules."""
        batch_setup(
            paths=["/home/user/proj"],
            mcp_servers=["proj"],
            scope="user",
            target="sandbox",
        )
        assert sandbox_settings.exists()
        data = _read_settings(sandbox_settings)
        assert "sandbox" in data
        assert "permissions" in data

    def test_idempotent(self, sandbox_settings: Path) -> None:
        batch_setup(
            paths=["/home/user/proj"],
            mcp_servers=["proj"],
            scope="user",
            target="sandbox",
        )
        result = batch_setup(
            paths=["/home/user/proj"],
            mcp_servers=["proj"],
            scope="user",
            target="sandbox",
        )
        assert "up to date" in result.lower()
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert aw.count("/home/user/proj") == 1
        allow = _read_allow(sandbox_settings)
        assert allow.count("mcp__proj__*") == 1

    def test_empty_lists_noop(self, sandbox_settings: Path) -> None:
        result = batch_setup(paths=[], mcp_servers=[], scope="user", target="sandbox")
        assert "nothing" in result.lower()

    def test_none_lists_noop(self, sandbox_settings: Path) -> None:
        result = batch_setup(scope="user", target="sandbox")
        assert "nothing" in result.lower()

    def test_mixed_new_and_existing(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/existing"]},
            },
            "permissions": {"allow": ["mcp__existing__*"]},
        })
        result = batch_setup(
            paths=["/home/user/existing", "/home/user/new"],
            mcp_servers=["existing", "new_srv"],
            scope="user",
            target="sandbox",
        )
        assert "Updated" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert aw.count("/home/user/existing") == 1
        assert "/home/user/new" in aw
        allow = _read_allow(sandbox_settings)
        assert allow.count("mcp__existing__*") == 1
        assert "mcp__new_srv__*" in allow

    def test_only_paths_no_mcp(self, sandbox_settings: Path) -> None:
        result = batch_setup(
            paths=["/home/user/proj"],
            mcp_servers=[],
            scope="user",
            target="sandbox",
        )
        assert "Updated" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/proj" in aw

    def test_only_mcp_no_paths(self, sandbox_settings: Path) -> None:
        result = batch_setup(
            paths=[],
            mcp_servers=["proj"],
            scope="user",
            target="sandbox",
        )
        assert "Updated" in result
        allow = _read_allow(sandbox_settings)
        assert "mcp__proj__*" in allow

    def test_strips_trailing_slashes(self, sandbox_settings: Path) -> None:
        batch_setup(
            paths=["/home/user/proj/"],
            mcp_servers=[],
            scope="user",
            target="sandbox",
        )
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/proj" in aw
        assert "/home/user/proj/" not in aw

    def test_auto_detects_sandbox(self, sandbox_settings: Path) -> None:
        result = batch_setup(
            paths=["/home/user/proj"],
            mcp_servers=["proj"],
            scope="user",
            target="auto",
        )
        assert "Updated" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/proj" in aw

    def test_large_lists(self, sandbox_settings: Path) -> None:
        paths = [f"/home/user/project{i}" for i in range(15)]
        servers = [f"server{i}" for i in range(8)]
        result = batch_setup(
            paths=paths, mcp_servers=servers, scope="user", target="sandbox"
        )
        assert "Updated" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert len(aw) == 15
        allow = _read_allow(sandbox_settings)
        assert len(allow) == 8

    def test_paths_with_special_chars(self, sandbox_settings: Path) -> None:
        batch_setup(
            paths=["/home/user/my project", "/home/user/path-with-dashes"],
            mcp_servers=[],
            scope="user",
            target="sandbox",
        )
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/my project" in aw
        assert "/home/user/path-with-dashes" in aw

    def test_settings_mode_mcp_only(self, user_settings: Path) -> None:
        """In settings mode (non-sandbox), only MCP rules are added (paths are ignored for sandbox)."""
        result = batch_setup(
            paths=["/home/user/proj"],
            mcp_servers=["proj"],
            scope="user",
            target="settings",
        )
        assert "Updated" in result
        allow = _read_allow(user_settings)
        assert "mcp__proj__*" in allow


# ---------------------------------------------------------------------------
# TestBatchRevoke — sandbox mode (paths + MCP rules)
# ---------------------------------------------------------------------------


class TestBatchRevoke:
    def test_removes_paths_and_mcp_rules(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/proj", "/home/user/other"]},
            },
            "permissions": {"allow": ["mcp__proj__*", "mcp__perms__*"]},
        })
        result = batch_revoke(
            paths=["/home/user/proj", "/home/user/other"],
            mcp_servers=["proj", "perms"],
            scope="user",
            target="sandbox",
        )
        assert "Revoked" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert aw == []
        allow = _read_allow(sandbox_settings)
        assert allow == []

    def test_idempotent_absent_entries(self, sandbox_settings: Path) -> None:
        result = batch_revoke(
            paths=["/nonexistent"],
            mcp_servers=["nonexistent"],
            scope="user",
            target="sandbox",
        )
        assert "No matching" in result or "nothing" in result.lower()

    def test_empty_lists_noop(self, sandbox_settings: Path) -> None:
        result = batch_revoke(paths=[], mcp_servers=[], scope="user", target="sandbox")
        assert "empty" in result.lower() or "nothing" in result.lower()

    def test_none_lists_noop(self, sandbox_settings: Path) -> None:
        result = batch_revoke(scope="user", target="sandbox")
        assert "empty" in result.lower() or "nothing" in result.lower()

    def test_partial_match_removes_only_present(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/keep", "/home/user/remove"]},
            },
            "permissions": {"allow": ["mcp__keep__*", "mcp__remove__*"]},
        })
        result = batch_revoke(
            paths=["/home/user/remove"],
            mcp_servers=["remove"],
            scope="user",
            target="sandbox",
        )
        assert "Revoked" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/keep" in aw
        assert "/home/user/remove" not in aw
        allow = _read_allow(sandbox_settings)
        assert "mcp__keep__*" in allow
        assert "mcp__remove__*" not in allow

    def test_only_paths_no_mcp(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/proj"]},
            },
            "permissions": {"allow": ["mcp__proj__*"]},
        })
        result = batch_revoke(
            paths=["/home/user/proj"],
            mcp_servers=[],
            scope="user",
            target="sandbox",
        )
        assert "Revoked" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/proj" not in aw
        allow = _read_allow(sandbox_settings)
        assert "mcp__proj__*" in allow  # MCP rule untouched

    def test_only_mcp_no_paths(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/proj"]},
            },
            "permissions": {"allow": ["mcp__proj__*"]},
        })
        result = batch_revoke(
            paths=[],
            mcp_servers=["proj"],
            scope="user",
            target="sandbox",
        )
        assert "Revoked" in result
        allow = _read_allow(sandbox_settings)
        assert "mcp__proj__*" not in allow
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/proj" in aw  # Sandbox path untouched

    def test_missing_settings_file(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """batch_revoke on a non-existent settings file is a no-op, no error."""
        nonexistent = tmp_path / "missing" / "settings.local.json"
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", nonexistent)
        monkeypatch.setattr(storage, "_USER_SETTINGS", tmp_path / "missing" / "settings.json")
        result = batch_revoke(
            paths=["/home/user/proj"],
            mcp_servers=["proj"],
            scope="user",
            target="sandbox",
        )
        assert "does not exist" in result or "nothing" in result.lower()
        assert not nonexistent.exists()

    def test_strips_trailing_slashes(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/proj"]},
            },
        })
        result = batch_revoke(
            paths=["/home/user/proj/"],
            scope="user",
            target="sandbox",
        )
        assert "Revoked" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert "/home/user/proj" not in aw

    def test_auto_detects_sandbox(self, sandbox_settings: Path) -> None:
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/proj"]},
            },
            "permissions": {"allow": ["mcp__proj__*"]},
        })
        result = batch_revoke(
            paths=["/home/user/proj"],
            mcp_servers=["proj"],
            scope="user",
            target="auto",
        )
        assert "Revoked" in result

    def test_large_lists(self, sandbox_settings: Path) -> None:
        paths = [f"/home/user/project{i}" for i in range(15)]
        servers = [f"server{i}" for i in range(8)]
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": paths},
            },
            "permissions": {"allow": [f"mcp__{s}__*" for s in servers]},
        })
        result = batch_revoke(
            paths=paths, mcp_servers=servers, scope="user", target="sandbox"
        )
        assert "Revoked" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert aw == []
        allow = _read_allow(sandbox_settings)
        assert allow == []

    def test_settings_mode_mcp_only(self, user_settings: Path) -> None:
        """In settings mode, only MCP rules are removed (paths are sandbox-only)."""
        _write_settings(user_settings, {
            "permissions": {"allow": ["mcp__proj__*", "Read(//home/user/proj/**)"]},
        })
        result = batch_revoke(
            paths=["/home/user/proj"],
            mcp_servers=["proj"],
            scope="user",
            target="settings",
        )
        assert "Revoked" in result
        allow = _read_allow(user_settings)
        assert "mcp__proj__*" not in allow
        assert "Read(//home/user/proj/**)" in allow  # Path rules untouched


# ---------------------------------------------------------------------------
# TestBatchRoundTrip — setup then revoke returns to clean state
# ---------------------------------------------------------------------------


class TestBatchRoundTrip:
    def test_setup_then_revoke_clean_state(self, sandbox_settings: Path) -> None:
        batch_setup(
            paths=["/home/user/proj", "/home/user/other"],
            mcp_servers=["proj", "perms"],
            scope="user",
            target="sandbox",
        )
        # Verify entries were added
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert len(aw) == 2
        allow = _read_allow(sandbox_settings)
        assert len(allow) == 2

        # Revoke everything
        result = batch_revoke(
            paths=["/home/user/proj", "/home/user/other"],
            mcp_servers=["proj", "perms"],
            scope="user",
            target="sandbox",
        )
        assert "Revoked" in result
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert aw == []
        allow = _read_allow(sandbox_settings)
        assert allow == []

    def test_setup_revoke_preserves_unrelated(self, sandbox_settings: Path) -> None:
        """Setup + revoke of specific entries does not affect unrelated entries."""
        _write_local_settings(sandbox_settings, {
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/unrelated"]},
            },
            "permissions": {"allow": ["mcp__unrelated__*"]},
        })
        batch_setup(
            paths=["/home/user/proj"],
            mcp_servers=["proj"],
            scope="user",
            target="sandbox",
        )
        batch_revoke(
            paths=["/home/user/proj"],
            mcp_servers=["proj"],
            scope="user",
            target="sandbox",
        )
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert aw == ["/home/user/unrelated"]
        allow = _read_allow(sandbox_settings)
        assert allow == ["mcp__unrelated__*"]

    def test_double_setup_single_revoke(self, sandbox_settings: Path) -> None:
        """Calling setup twice then revoking once leaves clean state (idempotent setup)."""
        for _ in range(2):
            batch_setup(
                paths=["/home/user/proj"],
                mcp_servers=["proj"],
                scope="user",
                target="sandbox",
            )
        batch_revoke(
            paths=["/home/user/proj"],
            mcp_servers=["proj"],
            scope="user",
            target="sandbox",
        )
        aw = _read_sandbox_allow_write(sandbox_settings)
        assert aw == []
        allow = _read_allow(sandbox_settings)
        assert allow == []
