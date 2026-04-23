"""Endpoint contracts for Todoist API v1 task endpoints.

URL, method, and request-body schemas come from the vendored OpenAPI
spec. Response schemas are kept hand-authored because the plugin's
``TodoistTask.to_dict`` translates raw API responses (notably converting
``priority: int`` to ``priority: "low|normal|high|urgent"``), so the
spec's response shape doesn't match what ``assert_response_parses`` sees.
"""

from __future__ import annotations

from tests.contracts import contract as _c

_TASK_RESPONSE_SCHEMA: dict[str, object] = {
    "properties": {
        "id": {"type": "string"},
        "content": {"type": "string"},
        "description": {"type": "string"},
        "priority": {"type": "string"},
        "labels": {"type": "array"},
        "due": {"type": ["object", "null"]},
        "project_id": {"type": "string"},
        "parent_id": {"type": ["string", "null"]},
        "is_completed": {"type": "boolean"},
        "updated_at": {"type": "string"},
    },
}

_OK_SCHEMA: dict[str, object] = {"properties": {"ok": {"type": "boolean"}}}


LIST_TASKS = _c(
    "GET",
    "/api/v1/tasks",
    response_schema={"items": _TASK_RESPONSE_SCHEMA},
)
CREATE_TASK = _c("POST", "/api/v1/tasks", response_schema=_TASK_RESPONSE_SCHEMA)
UPDATE_TASK = _c("POST", "/api/v1/tasks/{task_id}", response_schema=_TASK_RESPONSE_SCHEMA)
CLOSE_TASK = _c("POST", "/api/v1/tasks/{task_id}/close", status=204, response_schema=_OK_SCHEMA)
REOPEN_TASK = _c("POST", "/api/v1/tasks/{task_id}/reopen", status=204, response_schema=_OK_SCHEMA)
DELETE_TASK = _c("DELETE", "/api/v1/tasks/{task_id}", status=204, response_schema=_OK_SCHEMA)
GET_TASK = _c("GET", "/api/v1/tasks/{task_id}", response_schema=_TASK_RESPONSE_SCHEMA)
