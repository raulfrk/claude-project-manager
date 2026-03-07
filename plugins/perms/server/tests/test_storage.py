"""Tests for server.lib.storage."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from server.lib import storage
from server.lib.models import SettingsFile
from server.lib.storage import mcp_allow_entry


def test_allow_entries_for_path_adds_double_slash() -> None:
    entries = storage.allow_entries_for_path("/home/user/myproject")
    assert "Read(//home/user/myproject/**)" in entries
    assert "Edit(//home/user/myproject/**)" in entries


def test_allow_entries_strips_trailing_slash() -> None:
    a = storage.allow_entries_for_path("/home/user/proj/")
    b = storage.allow_entries_for_path("/home/user/proj")
    assert a == b


def test_allow_entries_rejects_relative_path() -> None:
    with pytest.raises(ValueError, match="absolute"):
        storage.allow_entries_for_path("relative/path")


def test_load_missing_file_returns_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nonexistent = tmp_path / "missing" / "settings.json"
    monkeypatch.setattr(storage, "_USER_SETTINGS", nonexistent)
    settings = storage.load("user")
    assert settings.permissions.allow == []
    assert not settings.path.exists()


def test_load_existing_file(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(
        json.dumps(
            {
                "model": "sonnet",
                "permissions": {"allow": ["Read(//home/user/proj/**)"]},
            }
        )
    )

    settings = storage.load("project", project_dir=tmp_path)
    assert settings.permissions.allow == ["Read(//home/user/proj/**)"]
    assert settings.raw.get("model") == "sonnet"


def test_save_creates_file_atomically(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    sf = SettingsFile(path=settings_path)
    sf.permissions.allow = ["Read(//tmp/**)"]
    storage.save(sf)

    assert settings_path.exists()
    data = json.loads(settings_path.read_text())
    assert data["permissions"]["allow"] == ["Read(//tmp/**)"]


def test_save_preserves_existing_keys(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"model": "opus", "permissions": {}}))

    settings = storage.load("project", project_dir=tmp_path)
    settings.permissions.allow.append("Read(//foo/**)")
    storage.save(settings)

    data = json.loads(settings_path.read_text())
    assert data["model"] == "opus"
    assert "Read(//foo/**)" in data["permissions"]["allow"]


def test_mcp_allow_entry_format() -> None:
    assert mcp_allow_entry("proj") == "mcp__proj__*"
    assert mcp_allow_entry("claude_ai_Todoist") == "mcp__claude_ai_Todoist__*"


def test_mcp_allow_entry_rejects_empty() -> None:
    with pytest.raises(ValueError, match="empty"):
        mcp_allow_entry("")


def test_save_removes_empty_permissions(tmp_path: Path) -> None:
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text(json.dumps({"permissions": {"allow": []}}))

    settings = storage.load("project", project_dir=tmp_path)
    # permissions stays empty
    storage.save(settings)

    data = json.loads(settings_path.read_text())
    assert "permissions" not in data


def test_save_write_failure_reraises(tmp_path: Path) -> None:
    """An OSError during the write is re-raised to the caller."""
    settings_path = tmp_path / ".claude" / "settings.json"
    sf = SettingsFile(path=settings_path)
    sf.permissions.allow = ["Read(//tmp/**)"]

    with patch("os.fdopen", side_effect=OSError("disk full")):
        with pytest.raises(OSError, match="disk full"):
            storage.save(sf)


def test_save_write_failure_cleans_up_temp_file(tmp_path: Path) -> None:
    """When the write raises, the temp file is removed and does not linger."""
    settings_path = tmp_path / ".claude" / "settings.json"
    sf = SettingsFile(path=settings_path)
    sf.permissions.allow = ["Read(//tmp/**)"]

    with patch("os.fdopen", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            storage.save(sf)

    # No .tmp files should remain in the parent directory
    tmp_files = list(settings_path.parent.glob("*.tmp"))
    assert tmp_files == [], f"Temp files were not cleaned up: {tmp_files}"


def test_save_write_failure_does_not_corrupt_original(tmp_path: Path) -> None:
    """When the write raises, the original settings.json is left intact."""
    settings_path = tmp_path / ".claude" / "settings.json"
    settings_path.parent.mkdir(parents=True)
    original_content = json.dumps({"permissions": {"allow": ["Read(//original/**)"]}})
    settings_path.write_text(original_content)

    sf = SettingsFile(path=settings_path)
    sf.permissions.allow = ["Read(//new/**)"]

    with patch("os.fdopen", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            storage.save(sf)

    # Original file must be unchanged
    assert settings_path.read_text() == original_content


# ── Sandbox models & storage tests ────────────────────────────────────────────


from server.lib.models import SandboxConfig, SandboxFilesystem, SandboxNetwork


class TestSandboxFilesystem:
    def test_empty_to_dict(self) -> None:
        sf = SandboxFilesystem()
        assert sf.to_dict() == {}

    def test_to_dict_with_values(self) -> None:
        sf = SandboxFilesystem(
            allow_write=["/home/user/proj"],
            deny_write=["/etc"],
            deny_read=["/secret"],
        )
        d = sf.to_dict()
        assert d == {
            "allowWrite": ["/home/user/proj"],
            "denyWrite": ["/etc"],
            "denyRead": ["/secret"],
        }

    def test_from_dict(self) -> None:
        data = {"allowWrite": ["/a"], "denyWrite": ["/b"], "denyRead": ["/c"]}
        sf = SandboxFilesystem.from_dict(data)
        assert sf.allow_write == ["/a"]
        assert sf.deny_write == ["/b"]
        assert sf.deny_read == ["/c"]

    def test_from_dict_empty(self) -> None:
        sf = SandboxFilesystem.from_dict({})
        assert sf.allow_write == []
        assert sf.deny_write == []
        assert sf.deny_read == []


class TestSandboxConfig:
    def test_empty_to_dict(self) -> None:
        sc = SandboxConfig()
        assert sc.to_dict() == {}

    def test_enabled_to_dict(self) -> None:
        sc = SandboxConfig(enabled=True)
        assert sc.to_dict()["enabled"] is True

    def test_from_dict_full(self) -> None:
        data = {
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "allowUnsandboxedCommands": False,
            "filesystem": {
                "allowWrite": ["/tmp"],
                "denyWrite": ["/etc"],
            },
            "network": {
                "allowedDomains": ["example.com"],
                "allowUnixSockets": ["/var/run/docker.sock"],
            },
            "customKey": "preserved",
        }
        sc = SandboxConfig.from_dict(data)
        assert sc.enabled is True
        assert sc.auto_allow_bash_if_sandboxed is True
        assert sc.filesystem.allow_write == ["/tmp"]
        assert sc.filesystem.deny_write == ["/etc"]
        assert sc.network.allowed_domains == ["example.com"]
        assert sc.network.allow_unix_sockets == ["/var/run/docker.sock"]
        assert sc.raw.get("customKey") == "preserved"

    def test_round_trip_preserves_unknown_keys(self) -> None:
        data = {"enabled": True, "futureKey": "value"}
        sc = SandboxConfig.from_dict(data)
        d = sc.to_dict()
        assert d["futureKey"] == "value"
        assert d["enabled"] is True


class TestLoadLocal:
    def test_load_local_missing_file_returns_defaults(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        nonexistent = tmp_path / "missing" / "settings.local.json"
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", nonexistent)
        settings = storage.load_local("user")
        assert settings.permissions.allow == []
        assert settings.sandbox.enabled is False
        assert not settings.path.exists()

    def test_load_local_existing_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        local_path.parent.mkdir(parents=True)
        local_path.write_text(json.dumps({
            "permissions": {"allow": ["Bash(uv run:*)"]},
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/home/user/proj"]},
            },
        }))
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", local_path)
        settings = storage.load_local("user")
        assert settings.permissions.allow == ["Bash(uv run:*)"]
        assert settings.sandbox.enabled is True
        assert settings.sandbox.filesystem.allow_write == ["/home/user/proj"]

    def test_load_local_project_scope(self, tmp_path: Path) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        local_path.parent.mkdir(parents=True)
        local_path.write_text(json.dumps({
            "sandbox": {"enabled": True},
        }))
        settings = storage.load_local("project", project_dir=tmp_path)
        assert settings.sandbox.enabled is True


class TestSaveWithSandbox:
    def test_save_preserves_sandbox_section(self, tmp_path: Path) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        local_path.parent.mkdir(parents=True)
        local_path.write_text(json.dumps({
            "sandbox": {
                "enabled": True,
                "filesystem": {"allowWrite": ["/existing"]},
            },
        }))
        settings = storage.load_local("project", project_dir=tmp_path)
        settings.sandbox.filesystem.allow_write.append("/new/path")
        storage.save(settings)

        data = json.loads(local_path.read_text())
        assert data["sandbox"]["enabled"] is True
        assert "/existing" in data["sandbox"]["filesystem"]["allowWrite"]
        assert "/new/path" in data["sandbox"]["filesystem"]["allowWrite"]

    def test_save_empty_sandbox_omitted(self, tmp_path: Path) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        sf = SettingsFile(path=local_path)
        sf.permissions.allow = ["Read(//tmp/**)"]
        storage.save(sf)

        data = json.loads(local_path.read_text())
        assert "sandbox" not in data


class TestIsSandboxEnabled:
    def test_false_when_no_local_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", tmp_path / "nonexistent.json")
        assert storage.is_sandbox_enabled("user") is False

    def test_true_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        local_path.parent.mkdir(parents=True)
        local_path.write_text(json.dumps({"sandbox": {"enabled": True}}))
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", local_path)
        assert storage.is_sandbox_enabled("user") is True

    def test_false_when_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        local_path.parent.mkdir(parents=True)
        local_path.write_text(json.dumps({"sandbox": {"enabled": False}}))
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", local_path)
        assert storage.is_sandbox_enabled("user") is False


class TestResolveTarget:
    def test_settings_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", tmp_path / "nonexistent.json")
        assert storage.resolve_target("settings", "user") == "settings"

    def test_sandbox_passthrough(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", tmp_path / "nonexistent.json")
        assert storage.resolve_target("sandbox", "user") == "sandbox"

    def test_auto_resolves_to_sandbox_when_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local_path = tmp_path / ".claude" / "settings.local.json"
        local_path.parent.mkdir(parents=True)
        local_path.write_text(json.dumps({"sandbox": {"enabled": True}}))
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", local_path)
        assert storage.resolve_target("auto", "user") == "sandbox"

    def test_auto_resolves_to_settings_when_disabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(storage, "_USER_LOCAL_SETTINGS", tmp_path / "nonexistent.json")
        assert storage.resolve_target("auto", "user") == "settings"
