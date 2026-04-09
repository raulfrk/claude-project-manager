"""Checklist endpoint contracts for the Trello API."""

from __future__ import annotations

from test_contracts.base import EndpointContract

# -- POST /checklists -------------------------------------------------------
CREATE_CHECKLIST = EndpointContract(
    method="POST",
    url_pattern="/1/checklists",
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

# -- POST /checklists/{checklistId}/checkItems --------------------------------
ADD_CHECKLIST_ITEM = EndpointContract(
    method="POST",
    url_pattern="/1/checklists/{checklistId}/checkItems",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
            "state": {"type": "string"},
        },
    },
    response_status=200,
)

# -- PUT /cards/{cardId}/checklist/{checklistId}/checkItem/{itemId} ----------
UPDATE_CHECKLIST_ITEM = EndpointContract(
    method="PUT",
    url_pattern="/1/cards/{cardId}/checklist/{checklistId}/checkItem/{itemId}",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={
        "properties": {
            "id": {"type": "string"},
            "state": {"type": "string"},
        },
    },
    response_status=200,
)

# -- DELETE /checklists/{checklistId} ----------------------------------------
DELETE_CHECKLIST = EndpointContract(
    method="DELETE",
    url_pattern="/1/checklists/{checklistId}",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={},
    response_status=200,
)

# -- PUT /cards/{cardId}/checkItem/{itemId} (rename) -------------------------
RENAME_CHECKLIST_ITEM = EndpointContract(
    method="PUT",
    url_pattern="/1/cards/{cardId}/checkItem/{itemId}",
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

# -- DELETE /cards/{cardId}/checkItem/{itemId} --------------------------------
DELETE_CHECKLIST_ITEM = EndpointContract(
    method="DELETE",
    url_pattern="/1/cards/{cardId}/checkItem/{itemId}",
    required_headers={},
    auth_style="query_params",
    request_schema=None,
    response_schema={},
    response_status=200,
)

# -- PUT /checklists/{checklistId} (rename checklist) -------------------------
RENAME_CHECKLIST = EndpointContract(
    method="PUT",
    url_pattern="/1/checklists/{checklistId}",
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
