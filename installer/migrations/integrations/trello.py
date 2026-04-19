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
        cfg = _load_trello_cfg(_load_cfg(project))
        key = cfg.get("api_key")
        token = cfg.get("api_token")
        if not (key and token):
            result.aborted = True
            # Single synthetic failure w/ runbook — not one-per-action spam.
            result.failed.append(
                FailedAction(
                    actions[0],
                    "ConfigError",
                    (
                        "trello api_key/token not found in "
                        "~/.claude/trello.yaml or proj.yaml. Run "
                        "`/proj:trello-sync` on this project after "
                        "migration completes to push the flat "
                        "structure to Trello."
                    ),
                    retryable=False,
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
    """Load global integration config from `~/.claude/proj.yaml`."""
    import yaml
    from pathlib import Path

    config_path = Path.home() / ".claude" / "proj.yaml"
    if not config_path.exists():
        return {}
    try:
        return yaml.safe_load(config_path.read_text()) or {}
    except yaml.YAMLError:
        return {}


def _load_trello_cfg(project_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve Trello auth + sync config with ``~/.claude/trello.yaml`` priority.

    ``trello.yaml`` stores the bearer token under key ``token``; normalise to
    ``api_token`` so callers can use one key.

    Priority:
      1. ``~/.claude/trello.yaml`` (keys ``api_key`` + ``token``, normalised).
      2. ``project_cfg['sync']['trello']`` (legacy; keys ``api_key`` + ``api_token``).
      3. ``{}`` if neither yields usable fields.
    """
    import yaml
    from pathlib import Path

    trello_yaml = Path.home() / ".claude" / "trello.yaml"
    if trello_yaml.exists():
        try:
            raw = yaml.safe_load(trello_yaml.read_text())
            data = raw if isinstance(raw, dict) else {}
            api_key = str(data.get("api_key", "")).strip()
            token = str(data.get("token", "")).strip()
            if api_key or token:
                cfg: dict[str, Any] = {}
                if api_key:
                    cfg["api_key"] = api_key
                if token:
                    cfg["api_token"] = token
                # Preserve sync config that the plan stage reads (board_id, list_mappings).
                # These still come from proj.yaml since trello.yaml doesn't carry them.
                proj = project_cfg or {}
                plan_fields = proj.get("sync", {}).get("trello", {})
                for field_name in ("board_id", "list_mappings", "default_list"):
                    if field_name in plan_fields:
                        cfg[field_name] = plan_fields[field_name]
                return cfg
        except yaml.YAMLError:
            pass  # fall through to proj.yaml fallback

    proj = project_cfg or {}
    return dict(proj.get("sync", {}).get("trello", {}))


def _update_local_trello_card_id(todo_id: str, card_id: str) -> None:
    """Write new trello_card_id back into local todos.yaml + SQL.

    Uses proj plugin's storage layer (load_todos / save_todos) to stay consistent
    with the hybrid YAML+SQL store.  Requires cfg + project_name which are not
    available at this call-site signature level, so we load config from the
    default path via storage.load_config().  If any step fails we log a warning
    and continue — the local snapshot backup exists for manual recovery.
    """
    # Import lazily so the installer doesn't require proj plugin at import time
    try:
        from plugins.proj.server.server.lib import storage  # type: ignore[import-not-found]
    except ImportError as e:
        log.warning(
            "proj storage not importable; skipping local trello_card_id update for %s: %s",
            todo_id,
            e,
        )
        return

    # storage has no single-field updater; use load → patch → save pattern.
    # storage.update_todo_field does NOT exist — use save_todos after patching.
    try:
        cfg = storage.load_config()
        # Determine project name by scanning all tracked projects for the todo_id
        index = storage.load_index(cfg)
        for proj_name in index.projects:
            todos = storage.load_todos(cfg, proj_name)
            for todo in todos:
                if todo.id == todo_id:
                    todo.trello_card_id = card_id
                    storage.save_todos(cfg, proj_name, todos)
                    log.debug(
                        "updated trello_card_id for todo %s → %s", todo_id, card_id
                    )
                    return
        log.warning(
            "todo %s not found in any tracked project; skipping local update", todo_id
        )
    except Exception as e:
        log.warning("failed to update local trello_card_id for todo %s: %s", todo_id, e)
