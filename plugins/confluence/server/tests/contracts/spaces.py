"""Confluence space endpoint contracts."""

from __future__ import annotations

from test_contracts.base import EndpointContract

_CLOUD_HEADERS = {"Authorization": "Basic {b64_email_token}"}
_SERVER_HEADERS = {"Authorization": "Bearer {token}"}

_LIST_SCHEMA = {
    "properties": {
        "results": {"type": "array"},
        "size": {"type": "integer"},
    }
}

LIST_SPACES_CLOUD = EndpointContract(
    method="GET",
    url_pattern="/wiki/rest/api/space",
    required_headers=_CLOUD_HEADERS,
    auth_style="basic",
    request_schema=None,
    response_schema=_LIST_SCHEMA,
    response_status=200,
)

LIST_SPACES_SERVER = EndpointContract(
    method="GET",
    url_pattern="/rest/api/space",
    required_headers=_SERVER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema=_LIST_SCHEMA,
    response_status=200,
)
