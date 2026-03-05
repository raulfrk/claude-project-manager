"""Named constants for the proj plugin."""

from __future__ import annotations

from enum import Enum


class TodoStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Priority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


TERMINAL_STATUSES = frozenset({"done", "cancelled"})

MANUAL_TAG = "manual"
