"""List endpoint contracts for the Trello API."""

from __future__ import annotations

from test_contracts.base import EndpointContract

# -- GET /boards/{boardId}/lists ---------------------------------------------
GET_LISTS = EndpointContract(
    method="GET",
    url_pattern="/1/boards/{boardId}/lists",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "items": {
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
            },
        },
    },
    response_status=200,
)

# -- GET /lists/{listId} ----------------------------------------------------
GET_LIST = EndpointContract(
    method="GET",
    url_pattern="/1/lists/{listId}",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
        },
    },
    response_status=200,
)

# -- POST /lists -------------------------------------------------------------
CREATE_LIST = EndpointContract(
    method="POST",
    url_pattern="/1/lists",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
        },
    },
    response_status=200,
)

# -- PUT /lists/{listId} ----------------------------------------------------
UPDATE_LIST = EndpointContract(
    method="PUT",
    url_pattern="/1/lists/{listId}",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
        },
    },
    response_status=200,
)
