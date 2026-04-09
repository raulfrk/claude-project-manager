"""Board endpoint contracts for the Trello API."""

from __future__ import annotations

from test_contracts.base import EndpointContract

# -- GET /members/me/boards --------------------------------------------------
LIST_BOARDS = EndpointContract(
    method="GET",
    url_pattern="/1/members/me/boards",
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

# -- GET /boards/{boardId} ---------------------------------------------------
GET_BOARD = EndpointContract(
    method="GET",
    url_pattern="/1/boards/{boardId}",
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

# -- PUT /boards/{boardId} ---------------------------------------------------
UPDATE_BOARD = EndpointContract(
    method="PUT",
    url_pattern="/1/boards/{boardId}",
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

# -- GET /boards/{boardId}/members -------------------------------------------
GET_BOARD_MEMBERS = EndpointContract(
    method="GET",
    url_pattern="/1/boards/{boardId}/members",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "items": {
            "properties": {
                "id": {"type": "string"},
                "fullName": {"type": "string"},
            },
        },
    },
    response_status=200,
)
