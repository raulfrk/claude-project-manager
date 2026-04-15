"""Tests for plugins/proj/server/server/lib/sandbox/models.py."""

from __future__ import annotations

from pathlib import Path

from server.lib.sandbox.models import (
    Permissions,
    SandboxConfig,
    SandboxFilesystem,
    SandboxNetwork,
    SettingsFile,
)

# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


class TestPermissions:
    def test_defaults(self) -> None:
        p = Permissions()
        assert p.allow == []
        assert p.deny == []
        assert p.raw == {}

    def test_to_dict_empty(self) -> None:
        p = Permissions()
        assert p.to_dict() == {}

    def test_to_dict_with_allow(self) -> None:
        p = Permissions(allow=["Edit(//foo/**)"])
        d = p.to_dict()
        assert d["allow"] == ["Edit(//foo/**)"]
        assert "deny" not in d

    def test_to_dict_with_deny(self) -> None:
        p = Permissions(deny=["Edit(//secret/**)"])
        d = p.to_dict()
        assert d["deny"] == ["Edit(//secret/**)"]
        assert "allow" not in d

    def test_roundtrip_empty(self) -> None:
        p = Permissions()
        restored = Permissions.from_dict(p.to_dict())
        assert restored.allow == []
        assert restored.deny == []

    def test_roundtrip_populated(self) -> None:
        p = Permissions(allow=["Edit(//a/**)"], deny=["Edit(//b/**)"])
        restored = Permissions.from_dict(p.to_dict())
        assert restored.allow == ["Edit(//a/**)"]
        assert restored.deny == ["Edit(//b/**)"]

    def test_raw_preserved(self) -> None:
        data = {"allow": ["Edit(//x/**)"], "ask": True, "additionalDirectories": ["/tmp"]}
        p = Permissions.from_dict(data)
        assert p.raw == {"ask": True, "additionalDirectories": ["/tmp"]}
        d = p.to_dict()
        assert d["ask"] is True
        assert d["additionalDirectories"] == ["/tmp"]

    def test_non_list_allow_becomes_empty(self) -> None:
        p = Permissions.from_dict({"allow": "not-a-list"})
        assert p.allow == []

    def test_non_list_deny_becomes_empty(self) -> None:
        p = Permissions.from_dict({"deny": 42})
        assert p.deny == []


# ---------------------------------------------------------------------------
# SandboxFilesystem
# ---------------------------------------------------------------------------


class TestSandboxFilesystem:
    def test_defaults(self) -> None:
        fs = SandboxFilesystem()
        assert fs.allow_write == []
        assert fs.deny_write == []
        assert fs.raw == {}

    def test_to_dict_empty(self) -> None:
        assert SandboxFilesystem().to_dict() == {}

    def test_to_dict_allow_write(self) -> None:
        fs = SandboxFilesystem(allow_write=["/tmp"])
        d = fs.to_dict()
        assert d["allowWrite"] == ["/tmp"]
        assert "denyWrite" not in d

    def test_to_dict_deny_write(self) -> None:
        fs = SandboxFilesystem(deny_write=["/etc"])
        d = fs.to_dict()
        assert d["denyWrite"] == ["/etc"]
        assert "allowWrite" not in d

    def test_roundtrip_populated(self) -> None:
        fs = SandboxFilesystem(allow_write=["/tmp"], deny_write=["/etc"])
        restored = SandboxFilesystem.from_dict(fs.to_dict())
        assert restored.allow_write == ["/tmp"]
        assert restored.deny_write == ["/etc"]

    def test_raw_preserved(self) -> None:
        data = {"allowWrite": ["/tmp"], "denyRead": ["/secret"]}
        fs = SandboxFilesystem.from_dict(data)
        assert fs.raw == {"denyRead": ["/secret"]}
        d = fs.to_dict()
        assert d["denyRead"] == ["/secret"]

    def test_non_list_becomes_empty(self) -> None:
        fs = SandboxFilesystem.from_dict({"allowWrite": "bad", "denyWrite": None})
        assert fs.allow_write == []
        assert fs.deny_write == []


# ---------------------------------------------------------------------------
# SandboxNetwork
# ---------------------------------------------------------------------------


class TestSandboxNetwork:
    def test_defaults(self) -> None:
        net = SandboxNetwork()
        assert net.allowed_domains == []
        assert net.raw == {}

    def test_to_dict_empty(self) -> None:
        assert SandboxNetwork().to_dict() == {}

    def test_to_dict_with_domains(self) -> None:
        net = SandboxNetwork(allowed_domains=["example.com", "api.github.com"])
        d = net.to_dict()
        assert d["allowedDomains"] == ["example.com", "api.github.com"]

    def test_roundtrip(self) -> None:
        net = SandboxNetwork(allowed_domains=["a.com", "b.com"])
        restored = SandboxNetwork.from_dict(net.to_dict())
        assert restored.allowed_domains == ["a.com", "b.com"]

    def test_raw_preserved(self) -> None:
        data = {"allowedDomains": ["x.com"], "allowUnixSockets": True}
        net = SandboxNetwork.from_dict(data)
        assert net.raw == {"allowUnixSockets": True}
        d = net.to_dict()
        assert d["allowUnixSockets"] is True

    def test_non_list_domains_becomes_empty(self) -> None:
        net = SandboxNetwork.from_dict({"allowedDomains": "not-a-list"})
        assert net.allowed_domains == []


# ---------------------------------------------------------------------------
# SandboxConfig
# ---------------------------------------------------------------------------


class TestSandboxConfig:
    def test_defaults(self) -> None:
        sc = SandboxConfig()
        assert sc.enabled is False
        assert sc.auto_allow_bash_if_sandboxed is False
        assert sc.filesystem.allow_write == []
        assert sc.network.allowed_domains == []

    def test_to_dict_empty(self) -> None:
        # All defaults → empty dict (enabled=False suppressed)
        assert SandboxConfig().to_dict() == {}

    def test_to_dict_enabled(self) -> None:
        sc = SandboxConfig(enabled=True)
        d = sc.to_dict()
        assert d["enabled"] is True

    def test_to_dict_auto_allow(self) -> None:
        sc = SandboxConfig(auto_allow_bash_if_sandboxed=True)
        assert sc.to_dict()["autoAllowBashIfSandboxed"] is True

    def test_roundtrip_with_nested(self) -> None:
        sc = SandboxConfig(
            enabled=True,
            filesystem=SandboxFilesystem(allow_write=["/tmp"]),
            network=SandboxNetwork(allowed_domains=["example.com"]),
        )
        restored = SandboxConfig.from_dict(sc.to_dict())
        assert restored.enabled is True
        assert restored.filesystem.allow_write == ["/tmp"]
        assert restored.network.allowed_domains == ["example.com"]

    def test_raw_preserved(self) -> None:
        data = {"enabled": True, "excludedCommands": ["rm"]}
        sc = SandboxConfig.from_dict(data)
        assert sc.raw == {"excludedCommands": ["rm"]}
        d = sc.to_dict()
        assert d["excludedCommands"] == ["rm"]

    def test_non_dict_filesystem_becomes_default(self) -> None:
        sc = SandboxConfig.from_dict({"filesystem": "bad"})
        assert sc.filesystem.allow_write == []

    def test_non_dict_network_becomes_default(self) -> None:
        sc = SandboxConfig.from_dict({"network": 123})
        assert sc.network.allowed_domains == []


# ---------------------------------------------------------------------------
# SettingsFile
# ---------------------------------------------------------------------------


class TestSettingsFile:
    def test_defaults(self, tmp_path: Path) -> None:
        p = tmp_path / "settings.json"
        sf = SettingsFile(path=p)
        assert sf.permissions.allow == []
        assert sf.sandbox.enabled is False
        assert sf.raw == {}

    def test_to_dict_empty(self, tmp_path: Path) -> None:
        sf = SettingsFile(path=tmp_path / "settings.json")
        assert sf.to_dict() == {}

    def test_roundtrip_with_permissions_and_sandbox(self, tmp_path: Path) -> None:
        p = tmp_path / "settings.json"
        sf = SettingsFile(
            path=p,
            permissions=Permissions(allow=["Edit(//foo/**)"], deny=["Edit(//bar/**)"]),
            sandbox=SandboxConfig(
                enabled=True,
                filesystem=SandboxFilesystem(allow_write=["/tmp"]),
                network=SandboxNetwork(allowed_domains=["github.com"]),
            ),
        )
        restored = SettingsFile.from_dict(p, sf.to_dict())
        assert restored.permissions.allow == ["Edit(//foo/**)"]
        assert restored.permissions.deny == ["Edit(//bar/**)"]
        assert restored.sandbox.enabled is True
        assert restored.sandbox.filesystem.allow_write == ["/tmp"]
        assert restored.sandbox.network.allowed_domains == ["github.com"]

    def test_raw_preserves_unknown_keys(self, tmp_path: Path) -> None:
        p = tmp_path / "settings.json"
        data: dict[str, object] = {
            "permissions": {},
            "unknownTopLevel": {"foo": 1},
            "anotherKey": 42,
        }
        sf = SettingsFile.from_dict(p, data)
        assert sf.raw == {"unknownTopLevel": {"foo": 1}, "anotherKey": 42}
        d = sf.to_dict()
        assert d["unknownTopLevel"] == {"foo": 1}
        assert d["anotherKey"] == 42

    def test_from_dict_non_dict_permissions_becomes_default(self, tmp_path: Path) -> None:
        p = tmp_path / "settings.json"
        sf = SettingsFile.from_dict(p, {"permissions": "bad"})
        assert sf.permissions.allow == []

    def test_from_dict_non_dict_sandbox_becomes_default(self, tmp_path: Path) -> None:
        p = tmp_path / "settings.json"
        sf = SettingsFile.from_dict(p, {"sandbox": 99})
        assert sf.sandbox.enabled is False

    def test_to_dict_removes_permissions_key_when_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "settings.json"
        # Start with raw that has "permissions" key, but permissions are empty
        sf = SettingsFile(path=p, raw={"permissions": {}})
        d = sf.to_dict()
        # Empty permissions → key should be absent
        assert "permissions" not in d

    def test_to_dict_removes_sandbox_key_when_empty(self, tmp_path: Path) -> None:
        p = tmp_path / "settings.json"
        sf = SettingsFile(path=p, raw={"sandbox": {}})
        d = sf.to_dict()
        assert "sandbox" not in d
