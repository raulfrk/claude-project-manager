"""Jira issue read tools."""

from __future__ import annotations

import json

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client


def register(app: FastMCP) -> None:
    @app.tool(description="Search Jira issues using JQL.")
    def jira_search(jql: str, max_results: int = 50, start_at: int = 0) -> str:
        client = get_client()
        data = client.get(
            "/rest/api/2/search",
            params={
                "jql": jql,
                "maxResults": max_results,
                "startAt": start_at,
                "fields": "summary,description,priority,assignee,labels,duedate,status,issuetype,parent,subtasks",
            },
        )
        return json.dumps(data)

    @app.tool(description="Get a single Jira issue by key.")
    def jira_get_issue(issue_key: str) -> str:
        client = get_client()
        data = client.get(f"/rest/api/2/issue/{issue_key}")
        return json.dumps(data)

    @app.tool(description="Get comments on a Jira issue.")
    def jira_get_issue_comments(issue_key: str) -> str:
        client = get_client()
        data = client.get(f"/rest/api/2/issue/{issue_key}/comment")
        return json.dumps(data)

    @app.tool(description="Get all issues under a Jira epic.")
    def jira_get_epic_issues(epic_key: str, max_results: int = 50) -> str:
        client = get_client()
        jql = f"parent = {epic_key} ORDER BY priority DESC"
        data = client.get(
            "/rest/api/2/search",
            params={
                "jql": jql,
                "maxResults": max_results,
                "fields": "summary,description,priority,assignee,labels,duedate,status,issuetype,parent,subtasks",
            },
        )
        return json.dumps(data)

    @app.tool(
        description=(
            "Get open issues assigned to a user. "
            "Defaults to config default_user and allowed_project_keys if not provided."
        ),
    )
    def jira_get_user_issues(
        username: str = "",
        project_keys: list[str] | None = None,
        max_results: int = 50,
    ) -> str:
        client = get_client()
        cfg = client._config

        user = username or cfg.default_user
        if not user:
            return json.dumps({"error": "No username provided and no default_user configured."})

        jql_parts = [
            f"assignee = {user}",
            "status not in (Done, Closed, Resolved)",
        ]

        keys = project_keys or cfg.allowed_project_keys
        if keys:
            joined = ", ".join(keys)
            jql_parts.append(f"project in ({joined})")

        jql = " AND ".join(jql_parts) + " ORDER BY priority DESC"
        data = client.get(
            "/rest/api/2/search",
            params={
                "jql": jql,
                "maxResults": max_results,
                "fields": "summary,description,priority,assignee,labels,duedate,status,issuetype,parent,subtasks",
            },
        )
        return json.dumps(data)

    @app.tool(
        description=(
            "Bulk-create Jira issues using the bulk endpoint (POST /rest/api/2/issue/bulk). "
            "issues_json is a JSON string with an 'issueUpdates' array. "
            "Each entry has 'fields' with at minimum 'project.key', 'summary', 'issuetype.name'. "
            "Returns the Jira bulk-create response with created issue keys."
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

        data = client.post("/rest/api/2/issue/bulk", json_body=payload)
        return json.dumps(data)

    @app.tool(
        description=(
            "Bulk-update Jira issues. updates_json is a JSON string with an 'updates' array. "
            "Each entry has 'key' (issue key, required) and 'fields' (dict of fields to update). "
            "Loops PUT /rest/api/2/issue/{key} internally with rate limiting. "
            "Returns {successes: [...], failures: [...]}."
        ),
    )
    def jira_bulk_update_issues(updates_json: str) -> str:
        client = get_client()
        try:
            payload = json.loads(updates_json)
        except json.JSONDecodeError as exc:
            return json.dumps({"error": f"Invalid JSON: {exc}"})

        updates = payload.get("updates", [])
        if not updates:
            return json.dumps({"error": "Missing or empty 'updates' array in payload"})

        successes: list[dict[str, object]] = []
        failures: list[dict[str, object]] = []
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
            except Exception as exc:  # noqa: BLE001
                failures.append({"index": idx, "key": update.get("key", ""), "error": str(exc)})
        return json.dumps({"successes": successes, "failures": failures})
