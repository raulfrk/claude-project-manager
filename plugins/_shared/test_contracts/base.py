"""Dataclass contracts for API endpoint and error specifications."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EndpointContract:
    """Describes the expected shape of an API endpoint request/response pair.

    Used by builders to construct mock httpx.Response objects and by validators
    to assert that requests and parsed results conform to the contract.
    """

    method: str
    """HTTP method: GET, POST, PUT, DELETE."""

    url_pattern: str
    """URL path pattern, e.g. "/api/v1/tasks" or "/rest/api/3/issue/{issueIdOrKey}"."""

    required_headers: dict[str, str]
    """Headers that must be present, e.g. {"Authorization": "Bearer {token}"}."""

    auth_style: str
    """Authentication style: "bearer" or "query_params"."""

    request_schema: dict[str, object] | None
    """JSON schema for request body. None for GET/DELETE."""

    response_schema: dict[str, object]
    """JSON schema describing the expected response body structure."""

    response_status: int
    """Expected HTTP success status code (200, 201, 204)."""

    response_headers: dict[str, str] = field(default_factory=dict)
    """Optional response headers to include in built responses."""


@dataclass(frozen=True)
class ErrorContract:
    """Describes the expected shape of an API error response.

    Used by builders to construct error httpx.Response objects and by validators
    to check that plugins raise the correct exceptions.
    """

    status_code: int
    """HTTP error status code: 401, 403, 404, 429, 500."""

    response_body: dict[str, object]
    """Expected error response body shape."""

    extra_headers: dict[str, str]
    """Additional response headers, e.g. {"Retry-After": "30"} for 429."""

    expected_exception: str
    """Exception class name the plugin should raise for this error."""
