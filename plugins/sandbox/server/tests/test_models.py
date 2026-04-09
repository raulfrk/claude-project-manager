"""Tests for sandbox data models — round-trip, from_dict, to_dict."""

from __future__ import annotations

from pathlib import Path

from server.lib.models import (
    Permissions,
    SandboxConfig,
    SandboxFilesystem,
    SandboxNetwork,
    SettingsFile,
)


class TestPermissions:
    def test_roundtrip(self) -> None:
        data = {
            "allow": ["mcp__x__*"],
            "deny": ["Bash(rm *)"],
            "ask": ["Edit(*)"],
            "additionalDirectories": ["/tmp"],
        }
        p = Permissions.from_dict(data)
        assert p.allow == ["mcp__x__*"]
        assert p.deny == ["Bash(rm *)"]
        assert p.raw["ask"] == ["Edit(*)"]
        assert p.raw["additionalDirectories"] == ["/tmp"]
        out = p.to_dict()
        assert out["allow"] == ["mcp__x__*"]
        assert out["ask"] == ["Edit(*)"]
        assert out["additionalDirectories"] == ["/tmp"]

    def test_empty(self) -> None:
        p = Permissions.from_dict({})
        assert p.allow == []
        assert p.deny == []
        assert p.raw == {}
        assert p.to_dict() == {}


class TestSandboxFilesystem:
    def test_roundtrip_with_deny_write(self) -> None:
        data = {"allowWrite": ["/tmp"], "denyWrite": ["/etc"], "denyRead": ["/secret"]}
        fs = SandboxFilesystem.from_dict(data)
        assert fs.allow_write == ["/tmp"]
        assert fs.deny_write == ["/etc"]
        assert "denyRead" in fs.raw
        assert "allowWrite" not in fs.raw  # popped
        assert "denyWrite" not in fs.raw  # popped
        out = fs.to_dict()
        assert out["allowWrite"] == ["/tmp"]
        assert out["denyWrite"] == ["/etc"]
        assert out["denyRead"] == ["/secret"]


class TestSandboxNetwork:
    def test_roundtrip_preserves_raw(self) -> None:
        data = {"allowedDomains": ["github.com"], "allowUnixSockets": ["/tmp/sock"]}
        net = SandboxNetwork.from_dict(data)
        assert net.allowed_domains == ["github.com"]
        assert "allowUnixSockets" in net.raw
        out = net.to_dict()
        assert out["allowedDomains"] == ["github.com"]
        assert out["allowUnixSockets"] == ["/tmp/sock"]


class TestSandboxConfig:
    def test_roundtrip_preserves_unknown(self) -> None:
        data = {
            "enabled": True,
            "autoAllowBashIfSandboxed": True,
            "excludedCommands": ["docker"],
            "filesystem": {"allowWrite": ["/tmp"]},
            "network": {"allowedDomains": ["gh.com"]},
        }
        cfg = SandboxConfig.from_dict(data)
        assert cfg.enabled is True
        assert cfg.raw["excludedCommands"] == ["docker"]
        out = cfg.to_dict()
        assert out["enabled"] is True
        assert out["excludedCommands"] == ["docker"]
        assert out["filesystem"]["allowWrite"] == ["/tmp"]


class TestSandboxConfigAutoAllow:
    def test_auto_allow_bash_roundtrip(self) -> None:
        data = {"enabled": True, "autoAllowBashIfSandboxed": True}
        cfg = SandboxConfig.from_dict(data)
        assert cfg.auto_allow_bash_if_sandboxed is True
        out = cfg.to_dict()
        assert out["autoAllowBashIfSandboxed"] is True

    def test_auto_allow_bash_defaults_false(self) -> None:
        cfg = SandboxConfig.from_dict({})
        assert cfg.auto_allow_bash_if_sandboxed is False
        out = cfg.to_dict()
        assert "autoAllowBashIfSandboxed" not in out


class TestSettingsFile:
    def test_from_dict_roundtrip(self) -> None:
        data = {
            "permissions": {"allow": ["mcp__x__*"], "ask": ["Edit(*)"]},
            "sandbox": {"enabled": True},
            "model": "claude-opus-4-6",
        }
        sf = SettingsFile.from_dict(Path("/tmp/test"), data)
        assert sf.permissions.allow == ["mcp__x__*"]
        assert sf.raw["model"] == "claude-opus-4-6"
        out = sf.to_dict()
        assert out["permissions"]["allow"] == ["mcp__x__*"]
        assert out["permissions"]["ask"] == ["Edit(*)"]
        assert out["model"] == "claude-opus-4-6"
