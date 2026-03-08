"""Data models for settings.json and settings.local.json structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path


@dataclass
class Permissions:
    allow: list[str] = field(default_factory=list)
    ask: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)
    additional_directories: list[str] = field(default_factory=list)  # round-trip preservation for Claude Code

    def to_dict(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        if self.allow:
            result["allow"] = self.allow
        if self.ask:
            result["ask"] = self.ask
        if self.deny:
            result["deny"] = self.deny
        if self.additional_directories:
            result["additionalDirectories"] = self.additional_directories
        return result

    @classmethod
    def from_dict(cls, data: dict[str, list[str]]) -> Permissions:
        return cls(
            allow=data.get("allow", []),
            ask=data.get("ask", []),
            deny=data.get("deny", []),
            additional_directories=data.get("additionalDirectories", []),
        )


@dataclass
class SandboxFilesystem:
    """Represents the ``sandbox.filesystem`` section of settings.local.json."""

    allow_write: list[str] = field(default_factory=list)
    deny_write: list[str] = field(default_factory=list)
    deny_read: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        if self.allow_write:
            result["allowWrite"] = self.allow_write
        if self.deny_write:
            result["denyWrite"] = self.deny_write
        if self.deny_read:
            result["denyRead"] = self.deny_read
        return result

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SandboxFilesystem:
        return cls(
            allow_write=list(data.get("allowWrite", [])),  # type: ignore[arg-type]
            deny_write=list(data.get("denyWrite", [])),  # type: ignore[arg-type]
            deny_read=list(data.get("denyRead", [])),  # type: ignore[arg-type]
        )


@dataclass
class SandboxNetwork:
    """Represents the ``sandbox.network`` section of settings.json."""

    allowed_domains: list[str] = field(default_factory=list)
    allow_unix_sockets: list[str] = field(default_factory=list)
    allow_all_unix_sockets: bool = False
    allow_local_binding: bool = False
    allow_managed_domains_only: bool = False
    http_proxy_port: int | None = None
    socks_proxy_port: int | None = None

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {}
        if self.allowed_domains:
            result["allowedDomains"] = self.allowed_domains
        if self.allow_unix_sockets:
            result["allowUnixSockets"] = self.allow_unix_sockets
        if self.allow_all_unix_sockets:
            result["allowAllUnixSockets"] = True
        if self.allow_local_binding:
            result["allowLocalBinding"] = True
        if self.allow_managed_domains_only:
            result["allowManagedDomainsOnly"] = True
        if self.http_proxy_port is not None:
            result["httpProxyPort"] = self.http_proxy_port
        if self.socks_proxy_port is not None:
            result["socksProxyPort"] = self.socks_proxy_port
        return result

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> SandboxNetwork:
        raw_sockets = data.get("allowUnixSockets", [])
        if isinstance(raw_sockets, bool):
            sockets: list[str] = []
        else:
            sockets = [str(s) for s in raw_sockets]  # type: ignore[union-attr]
        http_port = data.get("httpProxyPort")
        socks_port = data.get("socksProxyPort")
        return cls(
            allowed_domains=list(data.get("allowedDomains", [])),  # type: ignore[arg-type]
            allow_unix_sockets=sockets,
            allow_all_unix_sockets=bool(data.get("allowAllUnixSockets", False)),
            allow_local_binding=bool(data.get("allowLocalBinding", False)),
            allow_managed_domains_only=bool(data.get("allowManagedDomainsOnly", False)),
            http_proxy_port=int(http_port) if http_port is not None else None,  # type: ignore[arg-type]
            socks_proxy_port=int(socks_port) if socks_port is not None else None,  # type: ignore[arg-type]
        )


@dataclass
class SandboxConfig:
    """Represents the ``sandbox`` section of settings.json."""

    enabled: bool = False
    auto_allow_bash_if_sandboxed: bool = False
    allow_unsandboxed_commands: bool = False
    excluded_commands: list[str] = field(default_factory=list)
    enable_weaker_nested_sandbox: bool = False
    enable_weaker_network_isolation: bool = False
    filesystem: SandboxFilesystem = field(default_factory=SandboxFilesystem)
    network: SandboxNetwork = field(default_factory=SandboxNetwork)
    raw: dict[str, object] = field(default_factory=dict)  # unknown keys preserved for forward compatibility

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = dict(self.raw)
        if self.enabled:
            result["enabled"] = True
        if self.auto_allow_bash_if_sandboxed:
            result["autoAllowBashIfSandboxed"] = True
        if self.allow_unsandboxed_commands:
            result["allowUnsandboxedCommands"] = True
        if self.excluded_commands:
            result["excludedCommands"] = self.excluded_commands
        if self.enable_weaker_nested_sandbox:
            result["enableWeakerNestedSandbox"] = True
        if self.enable_weaker_network_isolation:
            result["enableWeakerNetworkIsolation"] = True
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
        known_keys = {
            "enabled", "autoAllowBashIfSandboxed", "allowUnsandboxedCommands",
            "excludedCommands", "enableWeakerNestedSandbox", "enableWeakerNetworkIsolation",
            "filesystem", "network",
        }
        raw = {k: v for k, v in data.items() if k not in known_keys}
        return cls(
            enabled=bool(data.get("enabled", False)),
            auto_allow_bash_if_sandboxed=bool(data.get("autoAllowBashIfSandboxed", False)),
            allow_unsandboxed_commands=bool(data.get("allowUnsandboxedCommands", False)),
            excluded_commands=list(data.get("excludedCommands", [])),  # type: ignore[arg-type]
            enable_weaker_nested_sandbox=bool(data.get("enableWeakerNestedSandbox", False)),
            enable_weaker_network_isolation=bool(data.get("enableWeakerNetworkIsolation", False)),
            filesystem=SandboxFilesystem.from_dict(fs_raw if isinstance(fs_raw, dict) else {}),
            network=SandboxNetwork.from_dict(net_raw if isinstance(net_raw, dict) else {}),
            raw=raw,
        )


@dataclass
class SettingsFile:
    path: Path
    permissions: Permissions = field(default_factory=Permissions)
    sandbox: SandboxConfig = field(default_factory=SandboxConfig)
    raw: dict[str, object] = field(default_factory=dict)  # unknown keys preserved for forward compatibility

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


Scope = Literal["user", "project"]
Target = Literal["settings", "sandbox", "auto"]

__all__ = [
    "Permissions",
    "SandboxConfig",
    "SandboxFilesystem",
    "SandboxNetwork",
    "Scope",
    "SettingsFile",
    "Target",
]
