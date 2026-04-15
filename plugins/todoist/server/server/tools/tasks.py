"""Todoist task MCP tools."""

import json
import logging

import httpx
from mcp.server.fastmcp import FastMCP

from server.lib.client import get_client
from server.lib.models import (
    JsonObject,
    JsonValue,
    TaskInput,
    TodoistTask,
    local_to_todoist_priority,
)

logger = logging.getLogger(__name__)

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
    # Unknown → default medium priority (p3), consistent with models.py
    return 3


def _to_json_value(val: str | int | float | bool | list[str] | None) -> JsonValue:
    """Convert a TaskInput value to a JsonValue, handling list[str] invariance."""
    if isinstance(val, list):
        return list(val)  # list[str] → list[JsonValue]
    return val


def _build_task_payload(task: TaskInput) -> JsonObject:
    """Build a Todoist REST API task creation/update payload from *task* dict."""
    payload: JsonObject = {}
    if "content" in task:
        payload["content"] = _to_json_value(task["content"])
    if "description" in task:
        payload["description"] = _to_json_value(task["description"])
    raw_priority = task.get("priority")
    priority = _resolve_priority(raw_priority) if isinstance(raw_priority, (str, int)) else None
    if priority is not None:
        payload["priority"] = priority
    if "labels" in task:
        payload["labels"] = _to_json_value(task["labels"])
    if "dueString" in task or "due_string" in task:
        payload["due_string"] = _to_json_value(task.get("dueString") or task.get("due_string"))
    if "projectId" in task or "project_id" in task:
        payload["project_id"] = _to_json_value(task.get("projectId") or task.get("project_id"))
    if "parentId" in task or "parent_id" in task:
        payload["parent_id"] = _to_json_value(task.get("parentId") or task.get("parent_id"))
    return payload


def register(app: FastMCP) -> None:
    """Register task tools on *app*."""

    @app.tool(
        description=(
            "Create multiple Todoist tasks. Each dict needs 'content' (required), "
            "plus optional description, priority (p1-p4 or high/medium/low), labels, "
            "dueString, projectId, parentId. "
            "Returns {successes: [...], failures: [...]}."
        ),
    )
    def todoist_add_tasks(tasks: list[TaskInput]) -> str:
        client = get_client()
        successes: list[JsonObject] = []
        failures: list[JsonObject] = []
        # Track created Todoist IDs by index so grandchildren can resolve
        # their parent's Todoist task ID via _parent_index.
        created_ids: dict[int, str] = {}
        for idx, task in enumerate(tasks):
            try:
                if not task.get("content"):
                    failures.append({"index": idx, "error": "Missing 'content'"})
                    continue
                # Resolve _parent_index → actual Todoist parent ID
                parent_index = task.get("_parent_index")
                if isinstance(parent_index, int) and parent_index >= 0:
                    resolved_parent = created_ids.get(parent_index)
                    if resolved_parent is None:
                        failures.append(
                            {
                                "index": idx,
                                "content": str(task.get("content", "")),
                                "error": f"Parent at index {parent_index} was not created",
                            }
                        )
                        continue
                    task = {**task, "parentId": resolved_parent}
                # Strip internal keys before building payload
                clean_task: TaskInput = {
                    k: v for k, v in task.items() if k not in ("_parent_index", "_local_id")
                }
                payload = _build_task_payload(clean_task)
                result = client.post("/tasks", json=payload)
                if not isinstance(result, dict):
                    failures.append({"index": idx, "error": "Unexpected response type"})
                    continue
                todoist_task = TodoistTask.from_api(result)
                created_ids[idx] = todoist_task.id
                successes.append(todoist_task.to_dict())
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning("Transient error adding task %d: %s", idx, exc)
                failures.append(
                    {
                        "index": idx,
                        "content": str(task.get("content", "")),
                        "error": f"transient: {exc}",
                    }
                )
            except (httpx.HTTPStatusError, RuntimeError) as exc:
                failures.append(
                    {
                        "index": idx,
                        "content": str(task.get("content", "")),
                        "error": str(exc),
                    }
                )
        return json.dumps({"successes": successes, "failures": failures})

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
            is_completed = task.get("checked", False) if isinstance(task, dict) else False
            return json.dumps(
                {
                    "verified": is_completed,
                    "task_id": todoist_task_id,
                    "status": "completed" if is_completed else "open",
                }
            )
        except Exception as exc:
            return json.dumps(
                {
                    "verified": False,
                    "task_id": todoist_task_id,
                    "status": "error",
                    "error": str(exc),
                }
            )

    @app.tool(
        description=(
            "Complete (close) multiple Todoist tasks by ID. "
            "Returns {successes: [...], failures: [...]}."
        ),
    )
    def todoist_complete_tasks(ids: list[str]) -> str:
        client = get_client()
        successes: list[JsonObject] = []
        failures: list[JsonObject] = []
        for task_id in ids:
            try:
                client.close_task(task_id)
                successes.append({"id": task_id})
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning("Transient error completing task %s: %s", task_id, exc)
                failures.append({"id": task_id, "error": f"transient: {exc}"})
            except (httpx.HTTPStatusError, RuntimeError) as exc:
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
        limit: int | None = None,
    ) -> str:
        client = get_client()
        params: dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        if filter:
            params["filter"] = filter
        raw_tasks = client.get_paginated("/tasks", params=params, limit=limit)
        tasks = [TodoistTask.from_api(t).to_dict() for t in raw_tasks if isinstance(t, dict)]
        return json.dumps(tasks)

    @app.tool(
        description=(
            "Update multiple Todoist tasks. Each dict needs 'id' (required), "
            "plus any changed fields (content, description, priority, labels, "
            "dueString). Returns {successes: [...], failures: [...]}."
        ),
    )
    def todoist_update_tasks(tasks: list[TaskInput]) -> str:
        client = get_client()
        successes: list[JsonObject] = []
        failures: list[JsonObject] = []
        for idx, task in enumerate(tasks):
            try:
                task_id = task.get("id")
                if not task_id:
                    failures.append({"index": idx, "error": "Missing 'id'"})
                    continue
                payload = _build_task_payload(task)
                result = client.post(f"/tasks/{task_id}", json=payload)
                if not isinstance(result, dict):
                    failures.append({"index": idx, "error": "Unexpected response type"})
                    continue
                successes.append(TodoistTask.from_api(result).to_dict())
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning("Transient error updating task %d: %s", idx, exc)
                failures.append(
                    {
                        "index": idx,
                        "id": str(task.get("id", "")),
                        "error": f"transient: {exc}",
                    }
                )
            except (httpx.HTTPStatusError, RuntimeError) as exc:
                failures.append(
                    {
                        "index": idx,
                        "id": str(task.get("id", "")),
                        "error": str(exc),
                    }
                )
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
        successes: list[JsonObject] = []
        failures: list[JsonObject] = []
        for task_id in ids:
            try:
                client.reopen_task(task_id)
                successes.append({"id": task_id})
            except (httpx.TimeoutException, httpx.ConnectError) as exc:
                logger.warning("Transient error reopening task %s: %s", task_id, exc)
                failures.append({"id": task_id, "error": f"transient: {exc}"})
            except (httpx.HTTPStatusError, RuntimeError) as exc:
                failures.append({"id": task_id, "error": str(exc)})
        return json.dumps({"successes": successes, "failures": failures})
