"""EndpointContract definitions for Todoist API v1 task endpoints."""

from __future__ import annotations

from test_contracts.base import EndpointContract

_AUTH_HEADERS = {"Authorization": "Bearer {token}"}
_AUTH_STYLE = "bearer"

# -- Task response schema (fields returned by TodoistTask.to_dict) -----------

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

# -- Contracts ---------------------------------------------------------------

LIST_TASKS = EndpointContract(
    method="GET",
    url_pattern="/api/v1/tasks",
    required_headers=_AUTH_HEADERS,
    auth_style=_AUTH_STYLE,
    request_schema=None,
    response_schema={"items": _TASK_RESPONSE_SCHEMA},
    response_status=200,
)

CREATE_TASK = EndpointContract(
    method="POST",
    url_pattern="/api/v1/tasks",
    required_headers=_AUTH_HEADERS,
    auth_style=_AUTH_STYLE,
    request_schema={
        "properties": {
            "content": {"type": "string"},
        },
    },
    response_schema=_TASK_RESPONSE_SCHEMA,
    response_status=200,
)

UPDATE_TASK = EndpointContract(
    method="POST",
    url_pattern="/api/v1/tasks/{task_id}",
    required_headers=_AUTH_HEADERS,
    auth_style=_AUTH_STYLE,
    request_schema={
        "properties": {
            "content": {"type": "string"},
        },
    },
    response_schema=_TASK_RESPONSE_SCHEMA,
    response_status=200,
)

CLOSE_TASK = EndpointContract(
    method="POST",
    url_pattern="/api/v1/tasks/{task_id}/close",
    required_headers=_AUTH_HEADERS,
    auth_style=_AUTH_STYLE,
    request_schema=None,
    response_schema={"properties": {"ok": {"type": "boolean"}}},
    response_status=204,
)

REOPEN_TASK = EndpointContract(
    method="POST",
    url_pattern="/api/v1/tasks/{task_id}/reopen",
    required_headers=_AUTH_HEADERS,
    auth_style=_AUTH_STYLE,
    request_schema=None,
    response_schema={"properties": {"ok": {"type": "boolean"}}},
    response_status=204,
)

DELETE_TASK = EndpointContract(
    method="DELETE",
    url_pattern="/api/v1/tasks/{task_id}",
    required_headers=_AUTH_HEADERS,
    auth_style=_AUTH_STYLE,
    request_schema=None,
    response_schema={"properties": {"ok": {"type": "boolean"}}},
    response_status=204,
)

GET_TASK = EndpointContract(
    method="GET",
    url_pattern="/api/v1/tasks/{task_id}",
    required_headers=_AUTH_HEADERS,
    auth_style=_AUTH_STYLE,
    request_schema=None,
    response_schema=_TASK_RESPONSE_SCHEMA,
    response_status=200,
)
