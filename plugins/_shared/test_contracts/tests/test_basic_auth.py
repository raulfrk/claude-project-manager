"""Tests for Basic auth style support in contract validators."""

from __future__ import annotations

import base64

import httpx
import pytest

from test_contracts.base import EndpointContract
from test_contracts.validators import assert_request_matches_contract


def test_basic_auth_style_accepted() -> None:
    contract = EndpointContract(
        method="GET",
        url_pattern="/rest/api/space",
        required_headers={"Authorization": "Basic {b64_email_token}"},
        auth_style="basic",
        request_schema=None,
        response_schema={"properties": {"results": {"type": "array"}}},
        response_status=200,
    )

    raw = base64.b64encode(b"u@example.com:tok").decode()
    req = httpx.Request(
        "GET",
        "https://x.example.com/rest/api/space",
        headers={"Authorization": f"Basic {raw}"},
    )

    assert_request_matches_contract(req, contract)  # no raise


def test_basic_auth_rejects_bearer() -> None:
    contract = EndpointContract(
        method="GET",
        url_pattern="/rest/api/space",
        required_headers={"Authorization": "Basic {b64_email_token}"},
        auth_style="basic",
        request_schema=None,
        response_schema={"properties": {}},
        response_status=200,
    )

    req = httpx.Request(
        "GET",
        "https://x.example.com/rest/api/space",
        headers={"Authorization": "Bearer token"},
    )

    with pytest.raises(AssertionError, match="Basic"):
        assert_request_matches_contract(req, contract)
