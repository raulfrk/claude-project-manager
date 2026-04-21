"""Confluence page endpoint contracts."""

from __future__ import annotations

from test_contracts.base import EndpointContract

_CLOUD_HEADERS = {"Authorization": "Basic {b64_email_token}"}
_SERVER_HEADERS = {"Authorization": "Bearer {token}"}

_PAGE_RESPONSE_SCHEMA = {
    "properties": {
        "id": {"type": "string"},
        "title": {"type": "string"},
        "version": {"type": "object"},
        "body": {"type": "object"},
    }
}

GET_PAGE_CLOUD = EndpointContract(
    method="GET",
    url_pattern="/wiki/rest/api/content/{id}",
    required_headers=_CLOUD_HEADERS,
    auth_style="basic",
    request_schema=None,
    response_schema=_PAGE_RESPONSE_SCHEMA,
    response_status=200,
)

GET_PAGE_SERVER = EndpointContract(
    method="GET",
    url_pattern="/rest/api/content/{id}",
    required_headers=_SERVER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema=_PAGE_RESPONSE_SCHEMA,
    response_status=200,
)

_CONTENT_LIST_SCHEMA = {
    "properties": {
        "results": {"type": "array"},
        "size": {"type": "integer"},
    }
}

GET_PAGE_BY_TITLE_CLOUD = EndpointContract(
    method="GET",
    url_pattern="/wiki/rest/api/content",
    required_headers=_CLOUD_HEADERS,
    auth_style="basic",
    request_schema=None,
    response_schema=_CONTENT_LIST_SCHEMA,
    response_status=200,
)

GET_PAGE_BY_TITLE_SERVER = EndpointContract(
    method="GET",
    url_pattern="/rest/api/content",
    required_headers=_SERVER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema=_CONTENT_LIST_SCHEMA,
    response_status=200,
)

# Placeholders for T14/T15 — add aliases now for future use
LIST_PAGES_CLOUD = GET_PAGE_BY_TITLE_CLOUD
LIST_PAGES_SERVER = GET_PAGE_BY_TITLE_SERVER

TREE_CLOUD = EndpointContract(
    method="GET",
    url_pattern="/wiki/rest/api/content/{id}/descendant/page",
    required_headers=_CLOUD_HEADERS,
    auth_style="basic",
    request_schema=None,
    response_schema=_CONTENT_LIST_SCHEMA,
    response_status=200,
)

TREE_SERVER = EndpointContract(
    method="GET",
    url_pattern="/rest/api/content/{id}/descendant/page",
    required_headers=_SERVER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema=_CONTENT_LIST_SCHEMA,
    response_status=200,
)
