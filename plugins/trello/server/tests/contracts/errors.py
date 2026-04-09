"""Error contracts for the Trello API."""

from __future__ import annotations

from test_contracts.base import ErrorContract

# -- 401 Unauthorized --------------------------------------------------------
UNAUTHORIZED = ErrorContract(
    status_code=401,
    response_body={"message": "unauthorized permission requested", "error": "ERROR"},
    extra_headers={},
    expected_exception="RuntimeError",
)

# -- 403 Forbidden -----------------------------------------------------------
FORBIDDEN = ErrorContract(
    status_code=403,
    response_body={"message": "insufficient permissions on resource", "error": "ERROR"},
    extra_headers={},
    expected_exception="RuntimeError",
)

# -- 404 Not Found -----------------------------------------------------------
NOT_FOUND = ErrorContract(
    status_code=404,
    response_body={"message": "The requested resource was not found.", "error": "ERROR"},
    extra_headers={},
    expected_exception="RuntimeError",
)

# -- 429 Rate Limited --------------------------------------------------------
RATE_LIMITED = ErrorContract(
    status_code=429,
    response_body={"message": "Rate limit exceeded", "error": "RATE_LIMIT_EXCEEDED"},
    extra_headers={"Retry-After": "10"},
    expected_exception="RuntimeError",
)

# -- 500 Server Error --------------------------------------------------------
SERVER_ERROR = ErrorContract(
    status_code=500,
    response_body={"message": "Internal server error", "error": "SERVER_ERROR"},
    extra_headers={},
    expected_exception="RuntimeError",
)
