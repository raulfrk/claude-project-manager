"""Data models for settings.json structures."""

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

    def to_dict(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        if self.allow:
            result["allow"] = self.allow
        if self.ask:
            result["ask"] = self.ask
        if self.deny:
            result["deny"] = self.deny
        return result

    @classmethod
    def from_dict(cls, data: dict[str, list[str]]) -> Permissions:
        return cls(
            allow=data.get("allow", []),
            ask=data.get("ask", []),
            deny=data.get("deny", []),
        )


@dataclass
class SettingsFile:
    path: Path
    permissions: Permissions = field(default_factory=Permissions)
    raw: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        result = dict(self.raw)
        perms = self.permissions.to_dict()
        if perms:
            result["permissions"] = perms
        else:
            result.pop("permissions", None)
        return result


Scope = Literal["user", "project"]

__all__ = ["Permissions", "Scope", "SettingsFile"]
