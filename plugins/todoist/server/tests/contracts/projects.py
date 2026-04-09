"""EndpointContract definitions for Todoist REST v2 project endpoints."""

from __future__ import annotations

from test_contracts.base import EndpointContract

_AUTH_HEADERS = {"Authorization": "Bearer {token}"}
_AUTH_STYLE = "bearer"

# -- Project response schema -------------------------------------------------

_PROJECT_RESPONSE_SCHEMA: dict[str, object] = {
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "color": {"type": ["string", "null"]},
        "is_favorite": {"type": "boolean"},
    },
}

# -- Contracts ---------------------------------------------------------------

LIST_PROJECTS = EndpointContract(
    method="GET",
    url_pattern="/api/v1/projects",
    required_headers=_AUTH_HEADERS,
    auth_style=_AUTH_STYLE,
    request_schema=None,
    response_schema={"items": _PROJECT_RESPONSE_SCHEMA},
    response_status=200,
)

CREATE_PROJECT = EndpointContract(
    method="POST",
    url_pattern="/api/v1/projects",
    required_headers=_AUTH_HEADERS,
    auth_style=_AUTH_STYLE,
    request_schema={
        "properties": {
            "name": {"type": "string"},
        },
    },
    response_schema=_PROJECT_RESPONSE_SCHEMA,
    response_status=200,
)
