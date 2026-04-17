# installer/migrations/integrations/trello.py
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

TRELLO_API = "https://api.trello.com/1"


class TrelloResync:
    name = "trello"

    def enabled_for(self, project: PendingProject) -> bool:
        cfg = _load_cfg(project)
        return bool(cfg.get("sync", {}).get("trello", {}).get("enabled"))

    def plan(self, project: PendingProject, migrated: list[TodoRef]) -> list[Action]:
        if not self.enabled_for(project):
            return []
        cfg = _load_cfg(project)["sync"]["trello"]
        parents_by_id: dict[str, TodoRef] = {
            t.id: t for t in migrated if t.trello_checklist_id
        }
        actions: list[Action] = []
        for child in migrated:
            if child.parent is None:
                continue
            parent = parents_by_id.get(child.parent)
            if parent is None:
                continue
            if not child.trello_checklist_item_id:
                log.warning(
                    "child %s missing trello_checklist_item_id; will be flat locally only",
                    child.id,
                )
                continue
            actions.append(
                Action(
                    kind="promote_checklist_item",
                    target_id=child.trello_checklist_item_id,
                    payload={
                        "parent_card_id": parent.trello_card_id,
                        "checklist_id": parent.trello_checklist_id,
                        "child_todo_id": child.id,
                        "title": child.title,
                        "board_id": cfg["board_id"],
                        "tasks_list_id": cfg["list_mappings"]["tasks"],
                    },
                ),
            )
        return actions

    def execute(self, project: PendingProject, actions: list[Action]) -> ResyncResult:
        result = ResyncResult()
        if not actions:
            return result
        cfg = _load_cfg(project)["sync"]["trello"]
        key = cfg.get("api_key")
        token = cfg.get("api_token")
        if not (key and token):
            result.aborted = True
            for a in actions:
                result.failed.append(
                    FailedAction(
                        a, "ConfigError", "trello api_key/token missing", False
                    ),
                )
            return result

        auth = {"key": key, "token": token}
        checklists_to_archive: set[str] = set()

        with httpx.Client(timeout=30.0) as client:
            for action in actions:
                try:
                    self._promote_one(client, auth, action)
                    result.ok.append(action)
                    checklists_to_archive.add(action.payload["checklist_id"])
                except httpx.HTTPStatusError as e:
                    retryable = e.response.status_code in (429, 500, 502, 503, 504)
                    result.failed.append(
                        FailedAction(
                            action,
                            "HTTPStatusError",
                            f"status={e.response.status_code}",
                            retryable,
                        ),
                    )
                    if e.response.status_code in (401, 403):
                        result.aborted = True
                        return result
                except httpx.RequestError as e:
                    result.failed.append(
                        FailedAction(action, "RequestError", str(e), True)
                    )

            # Archive emptied checklists
            for checklist_id in checklists_to_archive:
                try:
                    r = client.delete(
                        f"{TRELLO_API}/checklists/{checklist_id}",
                        params=auth,
                    )
                    r.raise_for_status()
                except httpx.HTTPError as e:
                    log.warning("failed to archive checklist %s: %s", checklist_id, e)

        return result

    def _promote_one(
        self,
        client: httpx.Client,
        auth: dict[str, str],
        action: Action,
    ) -> None:
        payload = action.payload
        # 1. Create new card on tasks list
        r = client.post(
            f"{TRELLO_API}/cards",
            params={
                **auth,
                "idList": payload["tasks_list_id"],
                "name": payload["title"],
            },
        )
        r.raise_for_status()
        new_card = r.json()
        # 2. Copy labels from parent card
        r = client.get(
            f"{TRELLO_API}/cards/{payload['parent_card_id']}/idLabels",
            params=auth,
        )
        r.raise_for_status()
        label_ids = r.json()
        for label_id in label_ids:
            cr = client.post(
                f"{TRELLO_API}/cards/{new_card['id']}/idLabels",
                params={**auth, "value": label_id},
            )
            if cr.status_code not in (200, 201):
                log.warning("failed to copy label %s to new card", label_id)
        # 3. Record new trello_card_id on local todo (via SQL update)
        _update_local_trello_card_id(
            action.payload["child_todo_id"],
            new_card["id"],
        )
        # 4. Delete checklist item
        r = client.delete(
            f"{TRELLO_API}/checklists/{payload['checklist_id']}/checkItems/{action.target_id}",
            params=auth,
        )
        r.raise_for_status()


def _load_cfg(project: PendingProject) -> dict[str, Any]:
    import yaml

    return yaml.safe_load(project.proj_yaml_path.read_text()) or {}


def _update_local_trello_card_id(todo_id: str, card_id: str) -> None:
    """Hook for updating local todo. Stubbed in Task 10 tests via monkeypatch;
    wired to proj storage in Task 12."""
    log.debug("TODO local update %s → %s", todo_id, card_id)
