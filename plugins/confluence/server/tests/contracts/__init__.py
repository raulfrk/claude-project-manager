"""Confluence API contract definitions.

Two specs are vendored:

- ``openapi/confluence-cloud-v3.json`` — official Atlassian Cloud spec,
  supplemented with ``confluence-cloud-supplement.json`` for endpoints
  the official spec omits (it skips the base
  ``/wiki/rest/api/content`` routes).
- ``openapi/confluence-dc-v1.json`` — hand-authored (no public spec
  exists for Confluence Server / DC).

Contracts come in pairs (``*_CLOUD`` / ``*_SERVER``) with identical
response shapes but different URL prefixes and auth styles.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from test_contracts.openapi import endpoint_contract, load_merged

if TYPE_CHECKING:
    from test_contracts.base import EndpointContract

_DIR = Path(__file__).parent / "openapi"
_CLOUD_SPEC = load_merged(
    _DIR / "confluence-cloud-v3.json",
    _DIR / "confluence-cloud-supplement.json",
)
_SERVER_SPEC = _DIR / "confluence-dc-v1.json"

_CLOUD_HEADERS = {"Authorization": "Basic {b64_email_token}"}
_SERVER_HEADERS = {"Authorization": "Bearer {token}"}


def cloud(method: str, url_pattern: str, *, status: str | int = "2xx") -> EndpointContract:
    """Build a Confluence Cloud endpoint contract."""
    return endpoint_contract(
        _CLOUD_SPEC,
        method,
        url_pattern,
        required_headers=_CLOUD_HEADERS,
        auth_style="basic",
        status=status,
        drop_required=True,
    )


def server(method: str, url_pattern: str, *, status: str | int = "2xx") -> EndpointContract:
    """Build a Confluence Server / DC endpoint contract."""
    return endpoint_contract(
        _SERVER_SPEC,
        method,
        url_pattern,
        required_headers=_SERVER_HEADERS,
        auth_style="bearer",
        status=status,
        drop_required=True,
    )
