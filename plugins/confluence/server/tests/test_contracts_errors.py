"""Error behavior contract tests."""

from __future__ import annotations

import httpx
import pytest
import respx

from server.lib.errors import (
    AuthError,
    NotFoundError,
    RateLimitError,
    ServerError,
)
from tests.contracts import errors as err


class TestErrorContracts:
    @respx.mock
    def test_401_raises_auth_error(self, server_client):
        respx.get(f"{server_client.api_base}/space").mock(
            return_value=httpx.Response(
                err.UNAUTHORIZED.status_code,
                json=err.UNAUTHORIZED.response_body,
            )
        )
        with pytest.raises(AuthError):
            server_client.get("/space", params={})

    @respx.mock
    def test_403_raises_auth_error(self, server_client):
        respx.get(f"{server_client.api_base}/space").mock(
            return_value=httpx.Response(
                err.FORBIDDEN.status_code,
                json=err.FORBIDDEN.response_body,
            )
        )
        with pytest.raises(AuthError):
            server_client.get("/space", params={})

    @respx.mock
    def test_404_raises_not_found(self, server_client):
        respx.get(f"{server_client.api_base}/content/42").mock(
            return_value=httpx.Response(
                err.NOT_FOUND.status_code,
                json=err.NOT_FOUND.response_body,
            )
        )
        with pytest.raises(NotFoundError):
            server_client.get("/content/42", params={})

    @respx.mock
    def test_429_retries_and_raises(self, server_client):
        respx.get(f"{server_client.api_base}/space").mock(
            return_value=httpx.Response(
                err.RATE_LIMITED.status_code,
                json=err.RATE_LIMITED.response_body,
                headers=err.RATE_LIMITED.extra_headers,
            )
        )
        with pytest.raises(RateLimitError) as exc_info:
            server_client.get("/space", params={})
        assert exc_info.value.retry_after == 1

    @respx.mock
    def test_500_raises_server_error(self, server_client):
        respx.get(f"{server_client.api_base}/space").mock(
            return_value=httpx.Response(
                err.SERVER_ERROR.status_code,
                json=err.SERVER_ERROR.response_body,
            )
        )
        with pytest.raises(ServerError):
            server_client.get("/space", params={})
