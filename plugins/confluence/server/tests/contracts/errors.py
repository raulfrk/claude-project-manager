"""Error response contracts for Confluence API."""

from __future__ import annotations

from test_contracts.base import ErrorContract

UNAUTHORIZED = ErrorContract(
    status_code=401,
    response_body={"message": "Unauthorized"},
    extra_headers={},
    expected_exception="AuthError",
)

FORBIDDEN = ErrorContract(
    status_code=403,
    response_body={"message": "Forbidden"},
    extra_headers={},
    expected_exception="AuthError",
)

NOT_FOUND = ErrorContract(
    status_code=404,
    response_body={"message": "Not found"},
    extra_headers={},
    expected_exception="NotFoundError",
)

RATE_LIMITED = ErrorContract(
    status_code=429,
    response_body={"message": "Rate limited"},
    extra_headers={"Retry-After": "1"},
    expected_exception="RateLimitError",
)

SERVER_ERROR = ErrorContract(
    status_code=500,
    response_body={"message": "Internal error"},
    extra_headers={},
    expected_exception="ServerError",
)
