"""Data models for Todoist tasks and projects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Self

# Recursive JSON type for unstructured API data
JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]
JsonObject = dict[str, JsonValue]

# Flat JSON dict usable in MCP tool signatures (pydantic-compatible — no recursion)
TaskInput = dict[str, str | int | float | bool | list[str] | None]

# -- Priority mapping ---------------------------------------------------------
# Consistent with plugins/proj/server/server/tools/todoist_sync.py lines 27-28.
# Todoist p1 is "urgent" but local has no urgent level, so p1 and p2 both map
# to "high".

_TODOIST_TO_LOCAL: dict[str, str] = {
    "p1": "high",
    "p2": "high",
    "p3": "medium",
    "p4": "low",
}

_LOCAL_TO_TODOIST: dict[str, str] = {
    "high": "p2",
    "medium": "p3",
    "low": "p4",
}


def local_to_todoist_priority(priority: str) -> str:
    """Convert a local priority string to a Todoist priority string.

    Mapping: high -> "p2", medium -> "p3", low -> "p4".
    Unknown values default to "p4".
    """
    return _LOCAL_TO_TODOIST.get(priority, "p4")


def todoist_to_local_priority(priority: str | int) -> str:
    """Convert a Todoist priority (string or int) to a local priority string.

    String mapping: p1 -> "high", p2 -> "high", p3 -> "medium", p4 -> "low".
    Int mapping: 1 -> "p1" -> "high", 2 -> "p2" -> "high", etc.
    Unknown/missing values default to "low".
    """
    if isinstance(priority, int):
        priority = f"p{priority}"
    if priority.startswith("p"):
        return _TODOIST_TO_LOCAL.get(priority, "low")
    return "low"


# -- Data models --------------------------------------------------------------


@dataclass
class TodoistTask:
    """Represents a Todoist task."""

    id: str
    content: str
    description: str = ""
    priority: str = "low"
    labels: list[str] = field(default_factory=list)
    due: JsonObject | None = None
    project_id: str = ""
    parent_id: str | None = None
    is_completed: bool = False
    updated_at: str = ""

    @classmethod
    def from_api(cls, data: JsonObject) -> Self:
        """Parse a Todoist API v1 task response into a TodoistTask."""
        raw_priority = data.get("priority")
        if isinstance(raw_priority, (str, int)):
            priority = todoist_to_local_priority(raw_priority)
        else:
            priority = "low"

        raw_labels = data.get("labels")
        labels: list[str] = [str(x) for x in raw_labels] if isinstance(raw_labels, list) else []

        due = data.get("due")
        if not isinstance(due, dict):
            due = None

        parent_raw = data.get("parent_id")
        parent_id = str(parent_raw) if parent_raw is not None else None

        return cls(
            id=str(data.get("id", "")),
            content=str(data.get("content", "")),
            description=str(data.get("description", "")),
            priority=priority,
            labels=labels,
            due=due,
            project_id=str(data.get("project_id", "")),
            parent_id=parent_id,
            is_completed=bool(data.get("checked", False)),
            updated_at=str(data.get("updated_at", "")),
        )

    def to_dict(self) -> JsonObject:
        """Serialize to a plain dictionary."""
        label_values: list[JsonValue] = list(self.labels)
        return {
            "id": self.id,
            "content": self.content,
            "description": self.description,
            "priority": self.priority,
            "labels": label_values,
            "due": self.due,
            "project_id": self.project_id,
            "parent_id": self.parent_id,
            "is_completed": self.is_completed,
            "updated_at": self.updated_at,
        }


@dataclass
class TodoistProject:
    """Represents a Todoist project."""

    id: str
    name: str
    color: str | None = None
    is_favorite: bool = False

    @classmethod
    def from_api(cls, data: JsonObject) -> Self:
        """Parse a Todoist API v1 project response into a TodoistProject."""
        color_raw = data.get("color")
        color = str(color_raw) if color_raw is not None else None
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            color=color,
            is_favorite=bool(data.get("is_favorite", False)),
        )

    def to_dict(self) -> JsonObject:
        """Serialize to a plain dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "is_favorite": self.is_favorite,
        }
