# installer/migrations/integrations/jira.py
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


class JiraResync:
    name = "jira"

    def enabled_for(self, project: PendingProject) -> bool:
        cfg = _load_cfg(project)
        return bool(cfg.get("sync", {}).get("jira", {}).get("enabled"))

    def plan(self, project: PendingProject, migrated: list[TodoRef]) -> list[Action]:
        if not self.enabled_for(project):
            return []
        by_id = {t.id: t for t in migrated if t.jira_issue_key}
        actions: list[Action] = []
        for child in migrated:
            if child.parent is None or child.jira_issue_key is None:
                continue
            parent = by_id.get(child.parent)
            if parent is None:
                continue
            # For Phase 1 we always try to preserve an epic link if present.
            # 'parent is Epic' inferred by convention (title-based or explicit
            # check could be done via API; kept simple here — parent's own
            # jira_issue_key is propagated as epic_link). Jira project may
            # reject the type conversion; that's a graceful per-issue failure.
            actions.append(
                Action(
                    kind="demote_subtask",
                    target_id=child.jira_issue_key,
                    payload={
                        "child_todo_id": child.id,
                        "epic_link": parent.jira_issue_key,
                        "new_issue_type": "Story",
                    },
                ),
            )
        return actions

    def execute(self, project: PendingProject, actions: list[Action]) -> ResyncResult:
        result = ResyncResult()
        if not actions:
            return result
        cfg = _load_jira_cfg(_load_cfg(project))
        base_url = cfg.get("base_url")
        email = cfg.get("email")
        token = cfg.get("api_token")
        missing = [
            key
            for key, val in (
                ("base_url", base_url),
                ("email", email),
                ("api_token", token),
            )
            if not val
        ]
        if missing:
            result.aborted = True
            # Single synthetic failure w/ runbook — not one-per-action spam.
            result.failed.append(
                FailedAction(
                    actions[0],
                    "ConfigError",
                    (
                        f"jira {', '.join(missing)} not found in "
                        "~/.claude/proj.yaml sync.jira block. Run "
                        "`/proj:jira-sync` on this project after "
                        "migration completes to push the flat "
                        "structure to Jira."
                    ),
                    retryable=False,
                ),
            )
            return result

        base = base_url.rstrip("/")
        epic_field = cfg.get("epic_link_field", "customfield_10014")

        auth = httpx.BasicAuth(email, token)
        with httpx.Client(base_url=base, timeout=30.0, auth=auth) as client:
            for action in actions:
                fields = {
                    "issuetype": {"name": action.payload["new_issue_type"]},
                    "parent": None,
                }
                if action.payload.get("epic_link"):
                    fields[epic_field] = action.payload["epic_link"]
                try:
                    r = client.put(
                        f"/rest/api/3/issue/{action.target_id}",
                        json={"fields": fields},
                    )
                    r.raise_for_status()
                    result.ok.append(action)
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
        return result


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


def _load_jira_cfg(project_cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Resolve Jira config with ``~/.claude/jira.yaml`` priority.

    Fields resolved: ``base_url``, ``email``, ``api_token`` (+ optional
    ``epic_link_field``). ``jira.yaml`` stores the token as
    ``personal_access_token``; normalise to ``api_token`` here so callers
    can use one key.

    Priority:
      1. ``~/.claude/jira.yaml``
      2. ``project_cfg['sync']['jira']`` (legacy)
      3. ``{}`` if neither yields usable fields.
    """
    import yaml
    from pathlib import Path

    jira_yaml = Path.home() / ".claude" / "jira.yaml"
    if jira_yaml.exists():
        try:
            raw = yaml.safe_load(jira_yaml.read_text())
            data = raw if isinstance(raw, dict) else {}
            token = str(data.get("personal_access_token", "")).strip()
            base_url = str(data.get("base_url", "")).strip()
            email = str(data.get("email", "")).strip()
            if token or base_url or email:
                cfg: dict[str, Any] = {}
                if base_url:
                    cfg["base_url"] = base_url
                if email:
                    cfg["email"] = email
                if token:
                    cfg["api_token"] = token
                epic_field = str(data.get("epic_link_field", "")).strip()
                if epic_field:
                    cfg["epic_link_field"] = epic_field
                return cfg
        except yaml.YAMLError:
            pass  # fall through to proj.yaml fallback

    proj = project_cfg or {}
    return dict(proj.get("sync", {}).get("jira", {}))
