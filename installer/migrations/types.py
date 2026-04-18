from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


TARGET_SCHEMA_VERSION = 3


class MigrationState(str, Enum):
    DISCOVERED = "discovered"
    PLANNED = "planned"
    CONFIRMED = "confirmed"
    SKIPPED = "skipped"
    BACKED_UP = "backed_up"
    FLATTENED = "flattened"
    RESYNCED = "resynced"
    COMMITTED = "committed"
    CLEANED = "cleaned"
    RESTORING = "restoring"
    FAILED = "failed"


class RecoveryPath(str, Enum):
    NORMAL = "normal"
    BUMP_ONLY = "bump_only"  # data already flat, only schema_version missing


@dataclass(frozen=True)
class PendingProject:
    name: str
    path: Path
    schema_version_path: Path  # was: proj_yaml_path
    current_version: int  # 1 or 0 (absent)

    def refreshed(self) -> "PendingProject":
        """Return a new PendingProject with current_version re-read from disk."""
        from installer.migrations.detect import read_schema_version

        v = read_schema_version(self.schema_version_path)
        return PendingProject(
            name=self.name,
            path=self.path,
            schema_version_path=self.schema_version_path,
            current_version=v if v is not None else self.current_version,
        )


@dataclass
class TodoRef:
    id: str
    title: str
    todoist_task_id: str | None = None
    trello_card_id: str | None = None
    trello_checklist_id: str | None = None
    trello_checklist_item_id: str | None = None
    jira_issue_key: str | None = None
    parent: str | None = None


@dataclass
class MigrationPlan:
    project: PendingProject
    parents: list[TodoRef] = field(default_factory=list)
    children: list[TodoRef] = field(default_factory=list)
    integration_actions: dict[str, list["Action"]] = field(default_factory=dict)  # noqa: F821
    recovery_path: RecoveryPath = RecoveryPath.NORMAL
