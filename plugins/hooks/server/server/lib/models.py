"""Data models for the hook registry."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Hook:
    """A single registered hook linking a trigger tool to a target tool."""

    id: str
    trigger_tool: str
    target_tool: str
    server: str
    param_mapping: dict[str, str] = field(default_factory=dict)
    blocking: bool = False
    condition: str | None = None
    source: str | None = None
    verification: bool = False
    feedback_mapping: dict[str, str] = field(default_factory=dict)
    feedback_tool: str | None = None

    def __post_init__(self) -> None:
        if self.verification:
            self.blocking = True

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {
            "id": self.id,
            "trigger_tool": self.trigger_tool,
            "target_tool": self.target_tool,
            "server": self.server,
            "param_mapping": self.param_mapping,
            "blocking": self.blocking,
        }
        if self.condition is not None:
            result["condition"] = self.condition
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
    def from_dict(cls, data: dict[str, object]) -> Hook:
        pm_raw = data.get("param_mapping", {})
        param_mapping: dict[str, str] = {}
        if isinstance(pm_raw, dict):
            param_mapping = {str(k): str(v) for k, v in pm_raw.items()}
        fm_raw = data.get("feedback_mapping", {})
        feedback_mapping: dict[str, str] = {}
        if isinstance(fm_raw, dict):
            feedback_mapping = {str(k): str(v) for k, v in fm_raw.items()}
        return cls(
            id=str(data.get("id", "")),
            trigger_tool=str(data.get("trigger_tool", "")),
            target_tool=str(data.get("target_tool", "")),
            server=str(data.get("server", "")),
            param_mapping=param_mapping,
            blocking=bool(data.get("blocking", False)),
            condition=str(data["condition"]) if data.get("condition") is not None else None,
            source=str(data["source"]) if data.get("source") is not None else None,
            verification=bool(data.get("verification", False)),
            feedback_mapping=feedback_mapping,
            feedback_tool=str(data["feedback_tool"]) if data.get("feedback_tool") is not None else None,
        )

    def update_from(self, new_def: dict) -> None:
        """Update content fields in-place from new_def. Preserves id, trigger_tool, target_tool, server, source."""
        if "blocking" in new_def:
            self.blocking = bool(new_def["blocking"])
        if "condition" in new_def:
            self.condition = str(new_def["condition"]) if new_def["condition"] is not None else None
        if "param_mapping" in new_def:
            self.param_mapping = {str(k): str(v) for k, v in (new_def["param_mapping"] or {}).items()}
        if "feedback_tool" in new_def:
            self.feedback_tool = str(new_def["feedback_tool"]) if new_def["feedback_tool"] is not None else None
        if "feedback_mapping" in new_def:
            self.feedback_mapping = {str(k): str(v) for k, v in (new_def["feedback_mapping"] or {}).items()}
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


@dataclass
class HookRegistry:
    """Top-level structure for hooks.yaml."""

    hooks: list[Hook] = field(default_factory=list)
    servers: dict[str, dict[str, str]] = field(default_factory=dict)
    settings: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        result: dict[str, object] = {}
        if self.hooks:
            result["hooks"] = [h.to_dict() for h in self.hooks]
        else:
            result["hooks"] = []
        if self.servers:
            result["servers"] = self.servers
        if self.settings:
            result["settings"] = self.settings
        return result

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> HookRegistry:
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
        settings: dict[str, object] = {}
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


__all__ = ["Hook", "HookRegistry"]
