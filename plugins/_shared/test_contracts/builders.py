"""Response factories for constructing httpx.Response objects from contracts."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from test_contracts.base import EndpointContract, ErrorContract

logger = logging.getLogger("test_contracts")


def build_success_response(
    contract: EndpointContract,
    data: dict[str, Any] | list[Any],
) -> httpx.Response:
    """Build an httpx.Response matching the contract's success specification.

    Args:
        contract: The endpoint contract defining status, headers, and schema.
        data: The JSON-serializable response body.

    Returns:
        An httpx.Response with the correct status code, headers, and JSON body.
    """
    headers = {"content-type": "application/json", **contract.response_headers}
    return httpx.Response(
        status_code=contract.response_status,
        headers=headers,
        content=json.dumps(data).encode("utf-8"),
    )


def build_error_response(error: ErrorContract) -> httpx.Response:
    """Build an httpx.Response matching the error contract specification.

    Args:
        error: The error contract defining status, body, and extra headers.

    Returns:
        An httpx.Response with the error status code, extra headers, and JSON body.
    """
    headers = {"content-type": "application/json", **error.extra_headers}
    return httpx.Response(
        status_code=error.status_code,
        headers=headers,
        content=json.dumps(error.response_body).encode("utf-8"),
    )


def build_paginated_response(
    contract: EndpointContract,
    items: list[dict[str, Any]],
    next_cursor: str | None = None,
) -> httpx.Response:
    """Build an httpx.Response with pagination metadata.

    Embeds items in the response body and adds pagination headers/fields.
    When ``next_cursor`` is provided, includes a ``next_cursor`` field in the
    body and an ``X-Next-Cursor`` response header.

    Args:
        contract: The endpoint contract defining status and headers.
        items: List of result items for the current page.
        next_cursor: Opaque cursor for the next page, or None if last page.

    Returns:
        An httpx.Response with paginated JSON body and optional cursor header.
    """
    body: dict[str, Any] = {
        "items": items,
        "total": len(items),
        "has_more": next_cursor is not None,
    }
    if next_cursor is not None:
        body["next_cursor"] = next_cursor

    headers = {"content-type": "application/json", **contract.response_headers}
    if next_cursor is not None:
        headers["X-Next-Cursor"] = next_cursor

    return httpx.Response(
        status_code=contract.response_status,
        headers=headers,
        content=json.dumps(body).encode("utf-8"),
    )
