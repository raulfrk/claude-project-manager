"""Named constants for the proj plugin."""

from __future__ import annotations

from enum import StrEnum


class TodoStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Priority(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


TERMINAL_STATUSES = frozenset({"done", "cancelled"})
