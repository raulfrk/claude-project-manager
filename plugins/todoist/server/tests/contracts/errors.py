"""ErrorContract definitions for Todoist REST v2 error responses."""

from __future__ import annotations

from test_contracts.base import ErrorContract

UNAUTHORIZED_401 = ErrorContract(
    status_code=401,
    response_body={"error": "Unauthorized"},
    extra_headers={},
    expected_exception="RuntimeError",
)

FORBIDDEN_403 = ErrorContract(
    status_code=403,
    response_body={"error": "Forbidden"},
    extra_headers={},
    expected_exception="RuntimeError",
)

NOT_FOUND_404 = ErrorContract(
    status_code=404,
    response_body={"error": "Not Found"},
    extra_headers={},
    expected_exception="RuntimeError",
)

RATE_LIMITED_429 = ErrorContract(
    status_code=429,
    response_body={"error": "Too Many Requests"},
    extra_headers={"Retry-After": "30"},
    expected_exception="RuntimeError",
)

SERVER_ERROR_500 = ErrorContract(
    status_code=500,
    response_body={"error": "Internal Server Error"},
    extra_headers={},
    expected_exception="RuntimeError",
)
