"""Error contracts for Jira API responses.

Covers standard Jira REST API error codes: 400, 401, 403, 404, 429, 500.
"""

from __future__ import annotations

from test_contracts.base import ErrorContract

BAD_REQUEST = ErrorContract(
    status_code=400,
    response_body={
        "errorMessages": ["Field 'summary' is required"],
        "errors": {"summary": "You must specify a summary of the issue."},
    },
    extra_headers={},
    expected_exception="RuntimeError",
)

UNAUTHORIZED = ErrorContract(
    status_code=401,
    response_body={
        "errorMessages": ["Login required"],
        "errors": {},
    },
    extra_headers={},
    expected_exception="RuntimeError",
)

FORBIDDEN = ErrorContract(
    status_code=403,
    response_body={
        "errorMessages": ["You do not have the permission to see the specified issue."],
        "errors": {},
    },
    extra_headers={},
    expected_exception="RuntimeError",
)

NOT_FOUND = ErrorContract(
    status_code=404,
    response_body={
        "errorMessages": ["Issue does not exist or you do not have permission to see it."],
        "errors": {},
    },
    extra_headers={},
    expected_exception="RuntimeError",
)

RATE_LIMITED = ErrorContract(
    status_code=429,
    response_body={
        "errorMessages": ["Rate limit exceeded"],
        "errors": {},
    },
    extra_headers={"Retry-After": "10"},
    expected_exception="RuntimeError",
)

SERVER_ERROR = ErrorContract(
    status_code=500,
    response_body={
        "errorMessages": ["Internal server error"],
        "errors": {},
    },
    extra_headers={},
    expected_exception="RuntimeError",
)
