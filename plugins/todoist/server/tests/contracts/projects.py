"""Endpoint contracts for Todoist API v1 project endpoints."""

from __future__ import annotations

from tests.contracts import contract as _c

_PROJECT_RESPONSE_SCHEMA: dict[str, object] = {
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "color": {"type": ["string", "null"]},
        "is_favorite": {"type": "boolean"},
    },
}

LIST_PROJECTS = _c(
    "GET",
    "/api/v1/projects",
    response_schema={"items": _PROJECT_RESPONSE_SCHEMA},
)
CREATE_PROJECT = _c("POST", "/api/v1/projects", response_schema=_PROJECT_RESPONSE_SCHEMA)
