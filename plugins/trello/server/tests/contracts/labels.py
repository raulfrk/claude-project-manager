"""Label endpoint contracts for the Trello API."""

from __future__ import annotations

from test_contracts.base import EndpointContract

# -- GET /boards/{boardId}/labels --------------------------------------------
GET_LABELS = EndpointContract(
    method="GET",
    url_pattern="/1/boards/{boardId}/labels",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "items": {
            "properties": {
                "id": {"type": "string"},
                "name": {"type": "string"},
                "color": {"type": "string"},
            },
        },
    },
    response_status=200,
)

# -- POST /labels ------------------------------------------------------------
CREATE_LABEL = EndpointContract(
    method="POST",
    url_pattern="/1/labels",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "color": {"type": "string"},
        },
    },
    response_status=200,
)

# -- PUT /labels/{labelId} --------------------------------------------------
UPDATE_LABEL = EndpointContract(
    method="PUT",
    url_pattern="/1/labels/{labelId}",
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

# -- DELETE /labels/{labelId} ------------------------------------------------
DELETE_LABEL = EndpointContract(
    method="DELETE",
    url_pattern="/1/labels/{labelId}",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={},
    response_status=200,
)
