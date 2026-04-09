"""Card endpoint contracts for the Trello API."""

from __future__ import annotations

from test_contracts.base import EndpointContract

# -- GET /lists/{listId}/cards -----------------------------------------------
GET_CARDS_BY_LIST = EndpointContract(
    method="GET",
    url_pattern="/1/lists/{listId}/cards",
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

# -- GET /cards/{cardId} -----------------------------------------------------
GET_CARD = EndpointContract(
    method="GET",
    url_pattern="/1/cards/{cardId}",
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

# -- POST /cards -------------------------------------------------------------
ADD_CARD = EndpointContract(
    method="POST",
    url_pattern="/1/cards",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "idList": {"type": "string"},
        },
    },
    response_status=200,
)

# -- PUT /cards/{cardId} (update) --------------------------------------------
UPDATE_CARD = EndpointContract(
    method="PUT",
    url_pattern="/1/cards/{cardId}",
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

# -- DELETE /cards/{cardId} --------------------------------------------------
DELETE_CARD = EndpointContract(
    method="DELETE",
    url_pattern="/1/cards/{cardId}",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={},
    response_status=200,
)

# -- POST /cards/{cardId}/idMembers -----------------------------------------
ADD_CARD_MEMBER = EndpointContract(
    method="POST",
    url_pattern="/1/cards/{cardId}/idMembers",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={},
    response_status=200,
)

# -- DELETE /cards/{cardId}/idMembers/{memberId} -----------------------------
REMOVE_CARD_MEMBER = EndpointContract(
    method="DELETE",
    url_pattern="/1/cards/{cardId}/idMembers/{memberId}",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={},
    response_status=200,
)

# -- POST /cards/{cardId}/idLabels ------------------------------------------
ADD_CARD_LABEL = EndpointContract(
    method="POST",
    url_pattern="/1/cards/{cardId}/idLabels",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={},
    response_status=200,
)

# -- DELETE /cards/{cardId}/idLabels/{labelId} -------------------------------
REMOVE_CARD_LABEL = EndpointContract(
    method="DELETE",
    url_pattern="/1/cards/{cardId}/idLabels/{labelId}",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={},
    response_status=200,
)

# -- GET /cards/{cardId}/actions (comments) ----------------------------------
GET_CARD_COMMENTS = EndpointContract(
    method="GET",
    url_pattern="/1/cards/{cardId}/actions",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "items": {
            "properties": {
                "id": {"type": "string"},
                "type": {"type": "string"},
            },
        },
    },
    response_status=200,
)

# -- POST /cards/{cardId}/actions/comments -----------------------------------
ADD_COMMENT = EndpointContract(
    method="POST",
    url_pattern="/1/cards/{cardId}/actions/comments",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "properties": {
            "id": {"type": "string"},
        },
    },
    response_status=200,
)

# -- GET /cards/{cardId}/attachments -----------------------------------------
GET_CARD_ATTACHMENTS = EndpointContract(
    method="GET",
    url_pattern="/1/cards/{cardId}/attachments",
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

# -- POST /cards/{cardId}/attachments ----------------------------------------
ADD_ATTACHMENT = EndpointContract(
    method="POST",
    url_pattern="/1/cards/{cardId}/attachments",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "properties": {
            "id": {"type": "string"},
        },
    },
    response_status=200,
)

# -- DELETE /cards/{cardId}/attachments/{attachmentId} -----------------------
DELETE_ATTACHMENT = EndpointContract(
    method="DELETE",
    url_pattern="/1/cards/{cardId}/attachments/{attachmentId}",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={},
    response_status=200,
)

# -- GET /cards/{cardId}/checklists ------------------------------------------
GET_CARD_CHECKLISTS = EndpointContract(
    method="GET",
    url_pattern="/1/cards/{cardId}/checklists",
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
