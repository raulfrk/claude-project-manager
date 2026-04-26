"""Data models for ~/.claude/settings.json (sandbox-mode only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class Permissions:
    """permissions section — only allow and deny are actively managed."""

    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    raw: dict[str, object] = field(
        default_factory=dict
    )  # preserves ask, additionalDirectories, etc.

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = dict(self.raw)
        if self.allow:
            result["allow"] = self.allow
        if self.deny:
            result["deny"] = list(self.deny)
        return result

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> Permissions:
        known_keys = {"allow", "deny"}
        raw = {k: v for k, v in data.items() if k not in known_keys}
        raw_allow = data.get("allow", [])
        raw_deny = data.get("deny", [])
        return cls(
            allow=list(raw_allow) if isinstance(raw_allow, list) else [],
            deny=list(raw_deny) if isinstance(raw_deny, list) else [],
            raw=raw,
        )


@dataclass
class SandboxFilesystem:
    """sandbox.filesystem section."""

    allow_write: list[str] = field(default_factory=list)
    deny_write: list[str] = field(default_factory=list)
    raw: dict[str, object] = field(default_factory=dict)  # preserves denyRead, allowRead, etc.

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = dict(self.raw)
        if self.allow_write:
            result["allowWrite"] = self.allow_write
        if self.deny_write:
            result["denyWrite"] = self.deny_write
        return result

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SandboxFilesystem:
        known_keys = {"allowWrite", "denyWrite"}
        raw = {k: v for k, v in data.items() if k not in known_keys}
        raw_aw = data.get("allowWrite", [])
        raw_dw = data.get("denyWrite", [])
        return cls(
            allow_write=list(raw_aw) if isinstance(raw_aw, list) else [],
            deny_write=list(raw_dw) if isinstance(raw_dw, list) else [],
            raw=raw,
        )


@dataclass
class SandboxNetwork:
    """sandbox.network section — only allowedDomains is actively managed."""

    allowed_domains: list[str] = field(default_factory=list)
    raw: dict[str, object] = field(
        default_factory=dict
    )  # preserves allowUnixSockets, proxy ports, etc.

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = dict(self.raw)
        if self.allowed_domains:
            result["allowedDomains"] = self.allowed_domains
        return result

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SandboxNetwork:
        known_keys = {"allowedDomains"}
        raw = {k: v for k, v in data.items() if k not in known_keys}
        raw_domains = data.get("allowedDomains", [])
        return cls(
            allowed_domains=list(raw_domains) if isinstance(raw_domains, list) else [],
            raw=raw,
        )


@dataclass
class SandboxConfig:
    """sandbox section of settings.json."""

    enabled: bool = False
    auto_allow_bash_if_sandboxed: bool = False
    filesystem: SandboxFilesystem = field(default_factory=SandboxFilesystem)
    network: SandboxNetwork = field(default_factory=SandboxNetwork)
    raw: dict[str, object] = field(
        default_factory=dict
    )  # preserves excludedCommands, enableWeaker*, etc.

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = dict(self.raw)
        if self.enabled:
            result["enabled"] = True
        if self.auto_allow_bash_if_sandboxed:
            result["autoAllowBashIfSandboxed"] = True
        fs = self.filesystem.to_dict()
        if fs:
            result["filesystem"] = fs
        net = self.network.to_dict()
        if net:
            result["network"] = net
        return result

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SandboxConfig:
        fs_raw = data.get("filesystem", {})
        net_raw = data.get("network", {})
        known_keys = {"enabled", "autoAllowBashIfSandboxed", "filesystem", "network"}
        raw = {k: v for k, v in data.items() if k not in known_keys}
        return cls(
            enabled=bool(data.get("enabled", False)),
            auto_allow_bash_if_sandboxed=bool(data.get("autoAllowBashIfSandboxed", False)),
            filesystem=SandboxFilesystem.from_dict(fs_raw if isinstance(fs_raw, dict) else {}),
            network=SandboxNetwork.from_dict(net_raw if isinstance(net_raw, dict) else {}),
            raw=raw,
        )


@dataclass
class SettingsFile:
    """Top-level ~/.claude/settings.json representation."""

    path: Path
    permissions: Permissions = field(default_factory=Permissions)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    raw: dict[str, object] = field(default_factory=dict)  # preserves unknown top-level keys

    def to_dict(self) -> dict[str, object]:
        result = dict(self.raw)
        perms = self.permissions.to_dict()
        if perms:
            result["permissions"] = perms
        else:
            result.pop("permissions", None)
        sandbox = self.sandbox.to_dict()
        if sandbox:
            result["sandbox"] = sandbox
        else:
            result.pop("sandbox", None)
        return result

    @classmethod
    def from_dict(cls, path: Path, data: dict[str, object]) -> SettingsFile:
        perms_raw = data.get("permissions", {})
        if not isinstance(perms_raw, dict):
            perms_raw = {}
        sandbox_raw = data.get("sandbox", {})
        if not isinstance(sandbox_raw, dict):
            sandbox_raw = {}
        raw = {k: v for k, v in data.items() if k not in ("permissions", "sandbox")}
        return cls(
            path=path,
            permissions=Permissions.from_dict(perms_raw),
            sandbox=SandboxConfig.from_dict(sandbox_raw),
            raw=raw,
        )


__all__ = [
    "Permissions",
    "SandboxConfig",
    "SandboxFilesystem",
    "SandboxNetwork",
    "SettingsFile",
]
