"""Scaffold dataclasses for managing ~/.claude/settings.json SessionStart hooks.

Diff and apply logic is in todo 488.3 (next batch). This module contains only
the data model, following the Permissions/SettingsFile raw-field preservation
pattern from plugins/sandbox/server/server/lib/models.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


class SettingsHooksError(Exception):
    """Raised when settings.json hooks cannot be read, parsed, or written."""


DiffKind = Literal["new", "changed", "removed", "unchanged"]


@dataclass
class SettingsHookDiff:
    """One row in the diff between desired and actual settings.json hook entries.

    cpm_id: the managed hook identifier (e.g. "proj-session-start-all")
    kind: new | changed | removed | unchanged
    desired: the resolved hook block from the plugin default (None if kind == "removed")
    actual: the current hook block in settings.json (None if kind == "new")
    event: e.g. "SessionStart"
    matchers: list of matcher names (e.g. ["startup", "resume", "clear", "compact"])
    """

    cpm_id: str
    kind: DiffKind
    event: str
    matchers: list[str]
    desired: dict[str, Any] | None = None
    actual: dict[str, Any] | None = None


@dataclass
class HooksBlock:
    """Structured view of the top-level `hooks:` section in settings.json.

    Preserves the full raw dict so round-tripping through from_dict/to_dict
    never loses unknown keys (mirrors Permissions.from_dict/to_dict in
    plugins/sandbox/server/server/lib/models.py lines 12-40).

    events: {event_name: [matcher_block, ...]} — parsed convenience view.
    raw: the underlying dict (source of truth for round-trips).
    """

    events: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict[str, Any] | None) -> "HooksBlock":
        if not d or not isinstance(d, dict):
            return cls()
        events: dict[str, list[dict[str, Any]]] = {}
        for event, matchers in d.items():
            if isinstance(matchers, list):
                events[event] = [m for m in matchers if isinstance(m, dict)]
        return cls(events=events, raw=dict(d))

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.raw)
        for event, matchers in self.events.items():
            result[event] = matchers
        return result


@dataclass
class SettingsDocument:
    """Full ~/.claude/settings.json document with HooksBlock as a structured view.

    raw holds all top-level keys (permissions, env, etc.). hooks is the parsed
    view that diff/apply logic consumes. to_dict round-trips through raw so
    non-hook keys are never lost.
    """

    path: Path
    hooks: HooksBlock = field(default_factory=HooksBlock)
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, path: Path, d: dict[str, Any] | None) -> "SettingsDocument":
        if not d or not isinstance(d, dict):
            return cls(path=path)
        hooks = HooksBlock.from_dict(d.get("hooks"))
        return cls(path=path, hooks=hooks, raw=dict(d))

    def to_dict(self) -> dict[str, Any]:
        result = dict(self.raw)
        result["hooks"] = self.hooks.to_dict()
        return result
