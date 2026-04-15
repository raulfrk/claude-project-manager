"""Jira issue read tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from server.lib.client import JsonValue, get_client

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

_DEFAULT_ISSUE_FIELDS = (
    "summary,description,priority,assignee,labels,duedate,status,issuetype,parent,subtasks"
)

_DEFAULT_DONE_STATUSES = ("Done", "Closed", "Resolved")


def _load_jira_yaml() -> dict[str, JsonValue]:
    """Load jira.yaml config, returning empty dict on missing/empty file."""
    config_path = Path("~/.claude/jira.yaml").expanduser()
    if not config_path.exists():
        return {}
    with config_path.open() as f:
        return yaml.safe_load(f) or {}


def _get_issue_fields() -> str:
    """Return issue fields string — from jira.yaml 'issue_fields' or default."""
    cfg = _load_jira_yaml()
    custom = cfg.get("issue_fields")
    if custom:
        if isinstance(custom, list):
            return ",".join(str(f) for f in custom)
        return str(custom)
    return _DEFAULT_ISSUE_FIELDS


def _get_done_statuses() -> tuple[str, ...]:
    """Return done-status values — from jira.yaml 'done_statuses' or default."""
    cfg = _load_jira_yaml()
    custom = cfg.get("done_statuses")
    if custom and isinstance(custom, list):
        return tuple(str(s) for s in custom)
    return _DEFAULT_DONE_STATUSES


def register(app: FastMCP) -> None:
    @app.tool(description="Search Jira issues using JQL.")
    def jira_search(jql: str, max_results: int = 50, start_at: int = 0) -> str:
        client = get_client()
        fields = _get_issue_fields()
        try:
            data = client.get(
                "/rest/api/2/search",
                params={
                    "jql": jql,
                    "maxResults": max_results,
                    "startAt": start_at,
                    "fields": fields,
                },
            )
            return json.dumps(data)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(description="Get a single Jira issue by key.")
    def jira_get_issue(issue_key: str) -> str:
        client = get_client()
        try:
            data = client.get(f"/rest/api/2/issue/{issue_key}")
            return json.dumps(data)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(description="Get comments on a Jira issue.")
    def jira_get_issue_comments(issue_key: str) -> str:
        client = get_client()
        try:
            data = client.get(f"/rest/api/2/issue/{issue_key}/comment")
            return json.dumps(data)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(description="Get all issues under a Jira epic (auto-paginates).")
    def jira_get_epic_issues(epic_key: str, page_size: int = 50) -> str:
        client = get_client()
        fields = _get_issue_fields()
        jql = f"parent = {epic_key} ORDER BY priority DESC"
        try:
            all_issues: list[JsonValue] = []
            start_at = 0
            while True:
                data = client.get(
                    "/rest/api/2/search",
                    params={
                        "jql": jql,
                        "maxResults": page_size,
                        "startAt": start_at,
                        "fields": fields,
                    },
                )
                if not isinstance(data, dict):
                    break
                issues = data.get("issues", [])
                if not isinstance(issues, list):
                    break
                all_issues.extend(issues)
                total = data.get("total", 0)
                if not isinstance(total, int):
                    break
                start_at += len(issues)
                if start_at >= total or not issues:
                    break
            return json.dumps({"issues": all_issues, "total": len(all_issues)})
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(
        description=(
            "Get open issues assigned to a user. "
            "Defaults to config default_user and allowed_project_keys if not provided."
        ),
    )
    def jira_get_user_issues(
        username: str = "",
        project_keys: list[str] | None = None,
        page_size: int = 50,
    ) -> str:
        client = get_client()
        cfg = client._config
        fields = _get_issue_fields()
        done_statuses = _get_done_statuses()

        user = username or cfg.default_user
        if not user:
            return json.dumps({"error": "No username provided and no default_user configured."})

        status_csv = ", ".join(done_statuses)
        jql_parts = [
            f"assignee = {user}",
            f"status not in ({status_csv})",
        ]

        keys = project_keys or cfg.allowed_project_keys
        if keys:
            joined = ", ".join(keys)
            jql_parts.append(f"project in ({joined})")

        jql = " AND ".join(jql_parts) + " ORDER BY priority DESC"
        try:
            all_issues: list[JsonValue] = []
            start_at = 0
            while True:
                data = client.get(
                    "/rest/api/2/search",
                    params={
                        "jql": jql,
                        "maxResults": page_size,
                        "startAt": start_at,
                        "fields": fields,
                    },
                )
                if not isinstance(data, dict):
                    break
                issues = data.get("issues", [])
                if not isinstance(issues, list):
                    break
                all_issues.extend(issues)
                total = data.get("total", 0)
                if not isinstance(total, int):
                    break
                start_at += len(issues)
                if start_at >= total or not issues:
                    break
            return json.dumps({"issues": all_issues, "total": len(all_issues)})
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(
        description=(
            "Create a single Jira issue with full field support including epic linking. "
            "Use parent_key to link the issue to an epic (Cloud/next-gen projects). "
            "For labels and components, pass comma-separated values."
        ),
    )
    def jira_create_issue(
        project_key: str,
        summary: str,
        issue_type: str = "Task",
        description: str | None = None,
        priority: str | None = None,
        assignee: str | None = None,
        parent_key: str | None = None,
        labels: str | None = None,
        components: str | None = None,
    ) -> str:
        client = get_client()
        fields: dict[str, JsonValue] = {
            "project": {"key": project_key},
            "summary": summary,
            "issuetype": {"name": issue_type},
        }
        if parent_key:
            fields["parent"] = {"key": parent_key}
        if description:
            fields["description"] = description
        if priority:
            fields["priority"] = {"name": priority}
        if assignee:
            fields["assignee"] = {"name": assignee}
        if labels:
            fields["labels"] = [lbl.strip() for lbl in labels.split(",")]
        if components:
            fields["components"] = [{"name": c.strip()} for c in components.split(",")]
        try:
            data = client.post("/rest/api/2/issue", json_body={"fields": fields})
            if not isinstance(data, dict):
                return json.dumps({"error": f"Unexpected response type: {type(data).__name__}"})
            return json.dumps({"key": data["key"], "self": data["self"]})
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(
        description=(
            "Bulk-create Jira issues using the bulk endpoint (POST /rest/api/2/issue/bulk). "
            "issues_json is a JSON string with an 'issueUpdates' array. "
            "Each entry has 'fields' with at minimum 'project.key', 'summary', 'issuetype.name'. "
            "Returns the Jira bulk-create response with created issue keys. "
            "Note: The bulk endpoint does not support epic linking via the parent field. "
            "Use jira_create_issue for individual issues that need epic links."
        ),
    )
    def jira_bulk_create_issues(issues_json: str) -> str:
        client = get_client()
        try:
            payload = json.loads(issues_json)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid JSON: {exc}"})

        if "issueUpdates" not in payload:
            return json.dumps({"error": "Missing 'issueUpdates' key in payload"})

        try:
            data = client.post("/rest/api/2/issue/bulk", json_body=payload)
            return json.dumps(data)
        except RuntimeError as exc:
            return json.dumps({"error": str(exc)})

    @app.tool(
        description=(
            "Update one or more Jira issues. updates_json is a JSON string with an 'updates' "
            "array. Each entry has 'key' (issue key, required) and 'fields' (dict of fields "
            "to update). Loops PUT /rest/api/2/issue/{key} for each entry. "
            "Returns {successes: [...], failures: [...]}."
        ),
    )
    def jira_update_issues(updates_json: str) -> str:
        client = get_client()
        try:
            payload = json.loads(updates_json)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid JSON: {exc}"})

        updates = payload.get("updates", [])
        if not updates:
            return json.dumps({"error": "Missing or empty 'updates' array in payload"})

        successes: list[dict[str, JsonValue]] = []
        failures: list[dict[str, JsonValue]] = []
        for idx, update in enumerate(updates):
            try:
                key = update.get("key", "")
                if not key:
                    failures.append({"index": idx, "error": "Missing 'key' field"})
                    continue
                fields = update.get("fields", {})
                if not fields:
                    failures.append({"index": idx, "key": key, "error": "No fields to update"})
                    continue
                client.put(f"/rest/api/2/issue/{key}", json_body={"fields": fields})
                successes.append({"key": key, "status": "updated"})
            except RuntimeError as exc:
                failures.append({"index": idx, "key": update.get("key", ""), "error": str(exc)})
        return json.dumps({"successes": successes, "failures": failures})
