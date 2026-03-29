"""Todoist task MCP tools."""

from __future__ import annotations

import json
from typing import Any

from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client
from server.lib.models import TodoistTask, local_to_todoist_priority

# Todoist REST API v2 expects priority as an integer 1-4.
# String "p1"-"p4" → strip "p" → int.
_TODOIST_PRIORITY_STRINGS = {"p1", "p2", "p3", "p4"}
_LOCAL_PRIORITY_NAMES = {"high", "medium", "low"}


def _resolve_priority(value: str | int | None) -> int | None:
    """Convert a priority value to the Todoist API integer (1-4).

    Accepts: int 1-4, Todoist strings "p1"-"p4", or local names
    "high"/"medium"/"low".  Returns None if *value* is None so callers
    can skip the field.
    """
    if value is None:
        return None
    if isinstance(value, int):
        return value
    v = str(value).strip().lower()
    if v in _TODOIST_PRIORITY_STRINGS:
        return int(v[1])
    if v in _LOCAL_PRIORITY_NAMES:
        todoist_str = local_to_todoist_priority(v)  # e.g. "p2"
        return int(todoist_str[1])
    # Unknown → default normal priority
    return 1


def _build_task_payload(task: dict[str, Any]) -> dict[str, Any]:
    """Build a Todoist REST API task creation/update payload from *task* dict."""
    payload: dict[str, Any] = {}
    if "content" in task:
        payload["content"] = task["content"]
    if "description" in task:
        payload["description"] = task["description"]
    priority = _resolve_priority(task.get("priority"))
    if priority is not None:
        payload["priority"] = priority
    if "labels" in task:
        payload["labels"] = task["labels"]
    if "dueString" in task or "due_string" in task:
        payload["due_string"] = task.get("dueString") or task.get("due_string")
    if "projectId" in task or "project_id" in task:
        payload["project_id"] = task.get("projectId") or task.get("project_id")
    if "parentId" in task or "parent_id" in task:
        payload["parent_id"] = task.get("parentId") or task.get("parent_id")
    return payload


def register(app: FastMCP) -> None:  # noqa: C901
    """Register task tools on *app*."""

    @app.tool(
        description=(
            "Create multiple Todoist tasks. Each dict needs 'content' (required), "
            "plus optional description, priority (p1-p4 or high/medium/low), labels, "
            "dueString, projectId, parentId. "
            "Returns {successes: [...], failures: [...]}."
        ),
    )
    def todoist_add_tasks(tasks: list[dict[str, Any]]) -> str:
        client = get_client()
        successes: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for idx, task in enumerate(tasks):
            try:
                if not task.get("content"):
                    failures.append({"index": idx, "error": "Missing 'content'"})
                    continue
                payload = _build_task_payload(task)
                result = client.post("/tasks", json=payload)
                successes.append(TodoistTask.from_api(result).to_dict())
            except Exception as exc:  # noqa: BLE001
                failures.append({
                    "index": idx,
                    "content": task.get("content", ""),
                    "error": str(exc),
                })
        return json.dumps({"successes": successes, "failures": failures})

    @app.tool(
        description=(
            "Hook-friendly single task creation. Accepts flat params: "
            "content (required), description, priority, labels, dueString, "
            "projectId, parentId. Calls the Todoist API directly (inlined)."
        ),
    )
    def todoist_add_task_hook(
        content: str,
        projectId: str | None = None,
        priority: str | int | None = None,
        labels: list[str] | None = None,
        description: str | None = None,
        dueString: str | None = None,
        parentId: str | None = None,
    ) -> str:
        task: dict[str, Any] = {"content": content}
        if projectId:
            task["projectId"] = projectId
        if priority:
            task["priority"] = priority
        if labels:
            task["labels"] = labels
        if description:
            task["description"] = description
        if dueString:
            task["dueString"] = dueString
        if parentId:
            task["parentId"] = parentId
        client = get_client()
        try:
            payload = _build_task_payload(task)
            result = client.post("/tasks", json=payload)
            return json.dumps({"successes": [TodoistTask.from_api(result).to_dict()], "failures": []})
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"successes": [], "failures": [{"content": content, "error": str(exc)}]})

    @app.tool(
        description=(
            "Hook-friendly single task completion. Accepts a single task ID "
            "and closes it via the Todoist API directly."
        ),
    )
    def todoist_complete_task_hook(id: str) -> str:
        client = get_client()
        try:
            client.close_task(id)
            return json.dumps({"successes": [{"id": id}], "failures": []})
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"successes": [], "failures": [{"id": id, "error": str(exc)}]})

    @app.tool(
        description=(
            "Hook-friendly single task update. Accepts flat params: "
            "id (required), plus optional content, priority, labels, "
            "description, dueString. Calls the Todoist API directly."
        ),
    )
    def todoist_update_task_hook(
        id: str,
        content: str | None = None,
        priority: str | int | None = None,
        labels: list[str] | None = None,
        description: str | None = None,
        dueString: str | None = None,
    ) -> str:
        task: dict[str, Any] = {"id": id}
        if content is not None:
            task["content"] = content
        if priority is not None:
            task["priority"] = priority
        if labels is not None:
            task["labels"] = labels
        if description is not None:
            task["description"] = description
        if dueString is not None:
            task["dueString"] = dueString
        client = get_client()
        try:
            payload = _build_task_payload(task)
            result = client.post(f"/tasks/{id}", json=payload)
            return json.dumps({"successes": [TodoistTask.from_api(result).to_dict()], "failures": []})
        except Exception as exc:  # noqa: BLE001
            return json.dumps({"successes": [], "failures": [{"id": id, "error": str(exc)}]})

    @app.tool(
        description=(
            "Verify that a Todoist task is completed. Fetches the task "
            "and checks its completion status. Returns JSON with "
            "verified (bool), task_id, and status."
        ),
    )
    def todoist_verify_complete(todoist_task_id: str) -> str:
        client = get_client()
        try:
            task = client.get(f"/tasks/{todoist_task_id}")
            is_completed = task.get("is_completed", False)
            return json.dumps({
                "verified": is_completed,
                "task_id": todoist_task_id,
                "status": "completed" if is_completed else "open",
            })
        except Exception as exc:  # noqa: BLE001
            return json.dumps({
                "verified": False,
                "task_id": todoist_task_id,
                "status": "error",
                "error": str(exc),
            })

    @app.tool(
        description=(
            "Complete (close) multiple Todoist tasks by ID. "
            "Returns {successes: [...], failures: [...]}."
        ),
    )
    def todoist_complete_tasks(ids: list[str]) -> str:
        client = get_client()
        successes: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for task_id in ids:
            try:
                client.close_task(task_id)
                successes.append({"id": task_id})
            except Exception as exc:  # noqa: BLE001
                failures.append({"id": task_id, "error": str(exc)})
        return json.dumps({"successes": successes, "failures": failures})

    @app.tool(
        description=(
            "Find Todoist tasks. Accepts optional project_id and filter string. "
            "Returns a JSON array of task objects."
        ),
    )
    def todoist_find_tasks(
        project_id: str | None = None,
        filter: str | None = None,
    ) -> str:
        client = get_client()
        params: dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        if filter:
            params["filter"] = filter
        response = client.get("/tasks", params=params or None)
        # API v1 returns {"results": [...]}, API v2 returns bare list
        if isinstance(response, dict) and "results" in response:
            raw_tasks = response["results"]
        elif isinstance(response, list):
            raw_tasks = response
        else:
            raw_tasks = []
        tasks = [TodoistTask.from_api(t).to_dict() for t in raw_tasks]
        return json.dumps(tasks)

    @app.tool(
        description=(
            "Update multiple Todoist tasks. Each dict needs 'id' (required), "
            "plus any changed fields (content, description, priority, labels, "
            "dueString). Returns {successes: [...], failures: [...]}."
        ),
    )
    def todoist_update_tasks(tasks: list[dict[str, Any]]) -> str:
        client = get_client()
        successes: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for idx, task in enumerate(tasks):
            try:
                task_id = task.get("id")
                if not task_id:
                    failures.append({"index": idx, "error": "Missing 'id'"})
                    continue
                payload = _build_task_payload(task)
                result = client.post(f"/tasks/{task_id}", json=payload)
                successes.append(TodoistTask.from_api(result).to_dict())
            except Exception as exc:  # noqa: BLE001
                failures.append({
                    "index": idx,
                    "id": task.get("id", ""),
                    "error": str(exc),
                })
        return json.dumps({"successes": successes, "failures": failures})

    @app.tool(description="Delete a single Todoist task by ID.")
    def todoist_delete(id: str) -> str:
        client = get_client()
        client.delete(f"/tasks/{id}")
        return json.dumps({"deleted": True, "id": id})

    @app.tool(
        description=(
            "Reopen (uncomplete) multiple Todoist tasks by ID. "
            "Returns {successes: [...], failures: [...]}."
        ),
    )
    def todoist_uncomplete_tasks(ids: list[str]) -> str:
        client = get_client()
        successes: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []
        for task_id in ids:
            try:
                client.reopen_task(task_id)
                successes.append({"id": task_id})
            except Exception as exc:  # noqa: BLE001
                failures.append({"id": task_id, "error": str(exc)})
        return json.dumps({"successes": successes, "failures": failures})
