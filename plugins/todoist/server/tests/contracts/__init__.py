"""Todoist API contract definitions.

Endpoint contracts are built from the vendored OpenAPI spec at
``openapi/todoist-v1.json`` (official, developer.todoist.com).

The official spec declares many required fields on response bodies that
don't map cleanly to our minimal test payloads, so contracts are built
with ``drop_required=True`` — we still validate types on fields that
are present, but don't demand the full required-field set. Required-
field drift is not caught; type drift on present fields is.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from test_contracts.openapi import endpoint_contract

if TYPE_CHECKING:
    from test_contracts.base import EndpointContract

_SPEC_PATH = Path(__file__).parent / "openapi" / "todoist-v1.json"
_BEARER = {"Authorization": "Bearer {token}"}


def contract(
    method: str,
    url_pattern: str,
    *,
    status: str | int = "2xx",
    response_schema: dict[str, object] | None = None,
) -> EndpointContract:
    """Build a Todoist endpoint contract from the vendored spec.

    ``response_schema`` may override the spec-derived schema when the
    plugin reshapes the server response on the way out (priority int
    → string etc.).
    """
    return endpoint_contract(
        _SPEC_PATH,
        method,
        url_pattern,
        required_headers=_BEARER,
        auth_style="bearer",
        status=status,
        drop_required=True,
        response_schema=response_schema,
    )
