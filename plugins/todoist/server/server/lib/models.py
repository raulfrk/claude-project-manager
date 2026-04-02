"""Data models for Todoist tasks and projects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Self

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
    if isinstance(priority, str) and priority.startswith("p"):
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
    due: dict[str, Any] | None = None
    project_id: str = ""
    parent_id: str | None = None
    is_completed: bool = False
    updated_at: str = ""

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        """Parse a Todoist REST API v2 task response into a TodoistTask."""
        raw_priority = data.get("priority")
        if raw_priority is not None:
            priority = todoist_to_local_priority(raw_priority)
        else:
            priority = "low"

        labels = data.get("labels")
        if not isinstance(labels, list):
            labels = []
        else:
            labels = [str(x) for x in labels]

        due = data.get("due")
        if not isinstance(due, dict):
            due = None

        return cls(
            id=str(data.get("id", "")),
            content=str(data.get("content", "")),
            description=str(data.get("description", "")),
            priority=priority,
            labels=labels,
            due=due,
            project_id=str(data.get("projectId", data.get("project_id", ""))),
            parent_id=data.get("parentId", data.get("parent_id")),
            is_completed=bool(data.get("isCompleted", data.get("is_completed", False))),
            updated_at=str(data.get("updatedAt", data.get("updated_at", ""))),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "id": self.id,
            "content": self.content,
            "description": self.description,
            "priority": self.priority,
            "labels": self.labels,
            "due": self.due,
            "project_id": self.project_id,
            "parent_id": self.parent_id,
            "is_completed": self.is_completed,
            "updatedAt": self.updated_at,
        }


@dataclass
class TodoistProject:
    """Represents a Todoist project."""

    id: str
    name: str
    color: str | None = None
    is_favorite: bool = False

    @classmethod
    def from_api(cls, data: dict[str, Any]) -> Self:
        """Parse a Todoist REST API v2 project response into a TodoistProject."""
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            color=data.get("color"),
            is_favorite=bool(data.get("isFavorite", data.get("is_favorite", False))),
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "is_favorite": self.is_favorite,
        }
