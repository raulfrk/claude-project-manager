# installer/migrations/integrations/todoist.py
from __future__ import annotations

import logging
from typing import Any

import httpx

from installer.migrations.integrations.base import (
    Action,
    FailedAction,
    ResyncResult,
)
from installer.migrations.types import PendingProject, TodoRef

log = logging.getLogger(__name__)

BATCH_SIZE = 50  # Todoist Sync API limit
TODOIST_API = "https://api.todoist.com/api/v1/sync"


class TodoistResync:
    name = "todoist"

    def enabled_for(self, project: PendingProject) -> bool:
        cfg = _load_cfg(project)
        if not cfg.get("sync", {}).get("todoist", {}).get("enabled"):
            return False
        # Also requires at least one todo with a todoist_task_id link
        import yaml

        todos = yaml.safe_load((project.path / "todos.yaml").read_text()) or []
        return any(t.get("todoist_task_id") for t in todos if isinstance(t, dict))

    def plan(self, project: PendingProject, migrated: list[TodoRef]) -> list[Action]:
        cfg = _load_cfg(project)
        if not cfg.get("sync", {}).get("todoist", {}).get("enabled"):
            return []
        actions: list[Action] = []
        for todo in migrated:
            if todo.parent is None or todo.todoist_task_id is None:
                continue
            actions.append(
                Action(
                    kind="clear_parent",
                    target_id=todo.todoist_task_id,
                    payload={"parent_id": None},
                ),
            )
        return actions

    def execute(self, project: PendingProject, actions: list[Action]) -> ResyncResult:
        result = ResyncResult()
        if not actions:
            return result
        cfg = _load_cfg(project)
        token = cfg["sync"]["todoist"].get("api_token")
        if not token:
            result.aborted = True
            for a in actions:
                result.failed.append(
                    FailedAction(
                        a, "ConfigError", "todoist api_token missing", retryable=False
                    ),
                )
            return result

        headers = {"Authorization": f"Bearer {token}"}
        with httpx.Client(timeout=30.0) as client:
            for start in range(0, len(actions), BATCH_SIZE):
                batch = actions[start : start + BATCH_SIZE]
                commands = [
                    {
                        "type": "item_move",
                        "uuid": f"mig-{a.target_id}",
                        "args": {"id": a.target_id, "parent_id": None},
                    }
                    for a in batch
                ]
                try:
                    resp = client.post(
                        TODOIST_API,
                        headers=headers,
                        json={"commands": commands},
                    )
                    resp.raise_for_status()
                    result.ok.extend(batch)
                except httpx.HTTPStatusError as e:
                    for a in batch:
                        result.failed.append(
                            FailedAction(
                                a,
                                "HTTPStatusError",
                                f"status={e.response.status_code}",
                                retryable=e.response.status_code
                                in (429, 500, 502, 503, 504),
                            ),
                        )
                    if e.response.status_code in (401, 403):
                        result.aborted = True
                        return result
                except httpx.RequestError as e:
                    for a in batch:
                        result.failed.append(
                            FailedAction(a, "RequestError", str(e), retryable=True),
                        )
        return result


def _load_cfg(project: PendingProject) -> dict[str, Any]:
    """Load global integration config from `~/.claude/proj.yaml`.

    Per-project files (meta.yaml) hold project IDs but the enable flags +
    api tokens live in the global config.
    """
    import yaml
    from pathlib import Path

    config_path = Path.home() / ".claude" / "proj.yaml"
    if not config_path.exists():
        return {}
    try:
        return yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError:
        return {}
