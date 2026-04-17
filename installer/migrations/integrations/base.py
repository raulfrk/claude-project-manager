from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from installer.migrations.types import PendingProject, TodoRef


@dataclass(frozen=True)
class Action:
    kind: str  # e.g. "clear_parent", "promote_checklist_item", "demote_subtask"
    target_id: str  # remote ID (todoist task, trello item, jira issue)
    payload: dict[str, Any]


@dataclass
class FailedAction:
    action: Action
    error_class: str
    message: str
    retryable: bool


@dataclass
class ResyncResult:
    ok: list[Action] = field(default_factory=list)
    failed: list[FailedAction] = field(default_factory=list)
    aborted: bool = False  # True when integration-wide failure stops further actions


@runtime_checkable
class IntegrationResync(Protocol):
    name: str  # "todoist" | "trello" | "jira"

    def enabled_for(self, project: PendingProject) -> bool: ...
    def plan(
        self, project: PendingProject, migrated: list[TodoRef]
    ) -> list[Action]: ...
    def execute(
        self, project: PendingProject, actions: list[Action]
    ) -> ResyncResult: ...
