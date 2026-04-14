"""Data models for the hook registry."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from server.lib._types import JsonValue


@dataclass
class Hook:
    """A single registered hook linking a trigger tool to a target tool."""

    id: str
    trigger_tool: str
    target_tool: str
    server: str
    param_mapping: dict[str, JsonValue] = field(default_factory=dict)
    blocking: bool = False
    condition: str | None = None
    result_condition: dict[str, JsonValue] | None = None
    source: str | None = None
    verification: bool = False
    feedback_mapping: dict[str, JsonValue] = field(default_factory=dict)
    feedback_tool: str | None = None

    def __post_init__(self) -> None:
        if self.verification:
            self.blocking = True

    def to_dict(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {
            "id": self.id,
            "trigger_tool": self.trigger_tool,
            "target_tool": self.target_tool,
            "server": self.server,
            "param_mapping": self.param_mapping,
            "blocking": self.blocking,
        }
        if self.condition is not None:
            result["condition"] = self.condition
        if self.result_condition is not None:
            result["result_condition"] = self.result_condition
        if self.source is not None:
            result["source"] = self.source
        if self.verification:
            result["verification"] = True
        if self.feedback_mapping:
            result["feedback_mapping"] = self.feedback_mapping
        if self.feedback_tool is not None:
            result["feedback_tool"] = self.feedback_tool
        return result

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> Hook:
        pm_raw = data.get("param_mapping", {})
        param_mapping: dict[str, JsonValue] = {}
        if isinstance(pm_raw, dict):
            param_mapping = {str(k): v for k, v in pm_raw.items()}
        fm_raw = data.get("feedback_mapping", {})
        feedback_mapping: dict[str, JsonValue] = {}
        if isinstance(fm_raw, dict):
            feedback_mapping = {str(k): v for k, v in fm_raw.items()}
        rc_raw = data.get("result_condition")
        result_condition: dict[str, JsonValue] | None = (
            {str(k): v for k, v in rc_raw.items()} if isinstance(rc_raw, dict) else None
        )
        return cls(
            id=str(data.get("id", "")),
            trigger_tool=str(data.get("trigger_tool", "")),
            target_tool=str(data.get("target_tool", "")),
            server=str(data.get("server", "")),
            param_mapping=param_mapping,
            blocking=bool(data.get("blocking", False)),
            condition=str(data["condition"]) if data.get("condition") is not None else None,
            result_condition=result_condition,
            source=str(data["source"]) if data.get("source") is not None else None,
            verification=bool(data.get("verification", False)),
            feedback_mapping=feedback_mapping,
            feedback_tool=str(data["feedback_tool"])
            if data.get("feedback_tool") is not None
            else None,
        )

    def update_from(self, new_def: dict[str, JsonValue]) -> None:
        """Update content fields in-place from new_def.

        Preserves id, trigger_tool, target_tool, server, source.
        """
        if "blocking" in new_def:
            self.blocking = bool(new_def["blocking"])
        if "condition" in new_def:
            self.condition = str(new_def["condition"]) if new_def["condition"] is not None else None
        if "result_condition" in new_def:
            rc = new_def["result_condition"]
            self.result_condition = (
                {str(k): v for k, v in rc.items()} if isinstance(rc, dict) else None
            )
        if "param_mapping" in new_def:
            pm = new_def["param_mapping"]
            self.param_mapping = {str(k): v for k, v in pm.items()} if isinstance(pm, dict) else {}
        if "feedback_tool" in new_def:
            self.feedback_tool = (
                str(new_def["feedback_tool"]) if new_def["feedback_tool"] is not None else None
            )
        if "feedback_mapping" in new_def:
            fm = new_def["feedback_mapping"]
            self.feedback_mapping = (
                {str(k): v for k, v in fm.items()} if isinstance(fm, dict) else {}
            )
        if "verification" in new_def:
            self.verification = bool(new_def["verification"])
        # Enforce invariant: verification implies blocking
        if self.verification:
            self.blocking = True

    def matches(self, trigger_tool: str, target_tool: str, server: str) -> bool:
        """Check if this hook matches the given trigger+target+server combination."""
        return (
            self.trigger_tool == trigger_tool
            and self.target_tool == target_tool
            and self.server == server
        )

    @property
    def is_numeric_id(self) -> bool:
        """Return True if this hook has an auto-generated numeric ID (hook-NNN)."""
        if not self.id.startswith("hook-"):
            return False
        try:
            int(self.id[5:])
            return True
        except ValueError:
            return False


@dataclass
class HookRegistry:
    """Top-level structure for hooks.yaml."""

    hooks: list[Hook] = field(default_factory=list)
    servers: dict[str, dict[str, str]] = field(default_factory=dict)
    settings: dict[str, JsonValue] = field(default_factory=dict)

    def to_dict(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {}
        if self.hooks:
            result["hooks"] = [h.to_dict() for h in self.hooks]
        else:
            result["hooks"] = []
        if self.servers:
            result["servers"] = cast("JsonValue", self.servers)
        if self.settings:
            result["settings"] = self.settings
        return result

    @classmethod
    def from_dict(cls, data: dict[str, JsonValue]) -> HookRegistry:
        hooks_raw = data.get("hooks", [])
        hooks: list[Hook] = []
        if isinstance(hooks_raw, list):
            hooks = [Hook.from_dict(h) for h in hooks_raw if isinstance(h, dict)]

        servers_raw = data.get("servers", {})
        servers: dict[str, dict[str, str]] = {}
        if isinstance(servers_raw, dict):
            for k, v in servers_raw.items():
                if isinstance(v, dict):
                    servers[str(k)] = {str(sk): str(sv) for sk, sv in v.items()}

        settings_raw = data.get("settings", {})
        settings: dict[str, JsonValue] = {}
        if isinstance(settings_raw, dict):
            settings = {str(k): v for k, v in settings_raw.items()}

        return cls(hooks=hooks, servers=servers, settings=settings)

    def next_id(self) -> str:
        """Generate the next hook-NNN id."""
        max_num = 0
        for hook in self.hooks:
            if hook.id.startswith("hook-"):
                try:
                    num = int(hook.id[5:])
                    max_num = max(max_num, num)
                except ValueError:
                    pass
        return f"hook-{max_num + 1:03d}"

    def find_duplicate(self, trigger_tool: str, target_tool: str, server: str) -> Hook | None:
        """Find an existing hook with the same trigger+target+server."""
        for hook in self.hooks:
            if hook.matches(trigger_tool, target_tool, server):
                return hook
        return None

    def find_by_id(self, hook_id: str) -> Hook | None:
        """Find a hook by its ID."""
        for hook in self.hooks:
            if hook.id == hook_id:
                return hook
        return None

    def remove_by_id(self, hook_id: str) -> bool:
        """Remove a hook by ID. Returns True if found and removed, False if not found."""
        before = len(self.hooks)
        self.hooks = [h for h in self.hooks if h.id != hook_id]
        return len(self.hooks) < before

    def find_all_duplicates(self, trigger_tool: str, target_tool: str, server: str) -> list[Hook]:
        """Find ALL hooks matching the given trigger+target+server."""
        return [h for h in self.hooks if h.matches(trigger_tool, target_tool, server)]

    def deduplicate_numeric_hooks(self) -> list[str]:
        """Remove numeric hook-NNN entries that duplicate a named hook.

        For each (trigger_tool, target_tool, server) group containing both
        numeric and named hooks, remove the numeric ones.

        Returns list of removed hook IDs.
        """
        from collections import defaultdict

        groups: defaultdict[tuple[str, str, str], list[Hook]] = defaultdict(list)
        for h in self.hooks:
            groups[(h.trigger_tool, h.target_tool, h.server)].append(h)

        removed_ids: list[str] = []
        for _key, group_hooks in groups.items():
            named = [h for h in group_hooks if not h.is_numeric_id]
            numeric = [h for h in group_hooks if h.is_numeric_id]
            if named and numeric:
                for h in numeric:
                    removed_ids.append(h.id)

        if removed_ids:
            remove_set = set(removed_ids)
            self.hooks = [h for h in self.hooks if h.id not in remove_set]

        return removed_ids


__all__ = ["Hook", "HookRegistry"]
