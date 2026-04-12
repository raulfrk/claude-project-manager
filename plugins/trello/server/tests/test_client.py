"""Tests for TrelloClient: auth params, rate limiting, error handling."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from server.lib.client import TrelloAPIError, TrelloClient, get_client
from server.lib.config import TrelloConfig


@pytest.fixture()
def config() -> TrelloConfig:
    return TrelloConfig(api_key="test-key", token="test-token", rate_limit_per_10s=100)


@pytest.fixture()
def client(config: TrelloConfig) -> TrelloClient:
    with patch("httpx.Client"):
        c = TrelloClient(config)
    # Replace the (mocked) httpx.Client instance with a fresh MagicMock
    # so we get clean call tracking per test.
    c._http = MagicMock()
    return c


def _ok_response(data: object = None) -> MagicMock:
    """Create a mock httpx.Response that looks successful."""
    resp = MagicMock(spec=httpx.Response)
    resp.is_success = True
    resp.status_code = 200
    resp.json.return_value = data if data is not None else {}
    return resp


def _error_response(status: int, text: str) -> MagicMock:
    """Create a mock httpx.Response that looks like an error."""
    resp = MagicMock(spec=httpx.Response)
    resp.is_success = False
    resp.status_code = status
    resp.text = text
    return resp


# ---------- Auth params ----------


class TestAuthParams:
    def test_auth_params_returns_key_token_dict(self, client: TrelloClient) -> None:
        result = client._auth_params()
        assert result == {"key": "test-key", "token": "test-token"}

    def test_auth_params_included_in_get(self, client: TrelloClient) -> None:
        client._http.request.return_value = _ok_response({"id": "b1"})

        client.get("/boards/b1")

        _, kwargs = client._http.request.call_args
        assert kwargs["params"]["key"] == "test-key"
        assert kwargs["params"]["token"] == "test-token"

    def test_auth_params_included_in_post(self, client: TrelloClient) -> None:
        client._http.request.return_value = _ok_response()

        client.post("/cards", params={"name": "c1"})

        _, kwargs = client._http.request.call_args
        params = kwargs["params"]
        assert params["key"] == "test-key"
        assert params["token"] == "test-token"
        assert params["name"] == "c1"

    def test_auth_params_included_in_put(self, client: TrelloClient) -> None:
        client._http.request.return_value = _ok_response()

        client.put("/cards/c1", params={"name": "updated"})

        _, kwargs = client._http.request.call_args
        params = kwargs["params"]
        assert params["key"] == "test-key"
        assert params["token"] == "test-token"
        assert params["name"] == "updated"

    def test_auth_params_included_in_delete(self, client: TrelloClient) -> None:
        client._http.request.return_value = _ok_response()

        client.delete("/cards/c1")

        _, kwargs = client._http.request.call_args
        assert kwargs["params"]["key"] == "test-key"
        assert kwargs["params"]["token"] == "test-token"

    def test_params_none_defaults_to_empty(self, client: TrelloClient) -> None:
        client._http.request.return_value = _ok_response([])

        client.get("/boards")

        _, kwargs = client._http.request.call_args
        assert kwargs["params"] == {"key": "test-key", "token": "test-token"}

    def test_post_merges_json_kwarg(self, client: TrelloClient) -> None:
        client._http.request.return_value = _ok_response()

        client.post("/cards", json={"name": "c1"})

        _, kwargs = client._http.request.call_args
        assert kwargs["json"] == {"name": "c1"}

    def test_put_merges_json_kwarg(self, client: TrelloClient) -> None:
        client._http.request.return_value = _ok_response()

        client.put("/cards/c1", json={"name": "updated"})

        _, kwargs = client._http.request.call_args
        assert kwargs["json"] == {"name": "updated"}


# ---------- Rate limiting ----------


class TestRateLimiting:
    def test_no_sleep_under_limit(self) -> None:
        config = TrelloConfig(api_key="k", token="t", rate_limit_per_10s=5)
        with patch("httpx.Client"):
            c = TrelloClient(config)
        c._http = MagicMock()
        c._http.request.return_value = _ok_response()

        with patch("server.lib.client.time.sleep") as mock_sleep:
            for _ in range(4):
                c.get("/boards")
            mock_sleep.assert_not_called()

    def test_sleeps_when_limit_exceeded(self) -> None:
        config = TrelloConfig(api_key="k", token="t", rate_limit_per_10s=2)
        with patch("httpx.Client"):
            c = TrelloClient(config)
        c._http = MagicMock()
        c._http.request.return_value = _ok_response()

        with patch("server.lib.client.time.sleep") as mock_sleep:
            c.get("/a")
            c.get("/b")
            # Third request should trigger rate limit
            c.get("/c")
            assert mock_sleep.call_count >= 1

    def test_old_timestamps_evicted(self) -> None:
        config = TrelloConfig(api_key="k", token="t", rate_limit_per_10s=2)
        with patch("httpx.Client"):
            c = TrelloClient(config)
        c._http = MagicMock()
        c._http.request.return_value = _ok_response()
        # Pre-populate with old timestamps (>10s ago)
        old = time.monotonic() - 15
        c._request_timestamps.append(old)
        c._request_timestamps.append(old)

        with patch("server.lib.client.time.sleep") as mock_sleep:
            c.get("/x")
            mock_sleep.assert_not_called()

    def test_timestamps_recorded(self) -> None:
        config = TrelloConfig(api_key="k", token="t", rate_limit_per_10s=100)
        with patch("httpx.Client"):
            c = TrelloClient(config)
        c._http = MagicMock()
        c._http.request.return_value = _ok_response()

        assert len(c._request_timestamps) == 0
        c.get("/a")
        assert len(c._request_timestamps) == 1
        c.get("/b")
        assert len(c._request_timestamps) == 2


# ---------- TrelloAPIError ----------


class TestTrelloAPIError:
    def test_is_runtime_error(self) -> None:
        err = TrelloAPIError(404, "Not Found")
        assert isinstance(err, RuntimeError)

    def test_has_status_code_and_text(self) -> None:
        err = TrelloAPIError(500, "Internal Server Error")
        assert err.status_code == 500
        assert err.text == "Internal Server Error"

    def test_message_format(self) -> None:
        err = TrelloAPIError(401, "Unauthorized")
        assert str(err) == "Trello API error 401: Unauthorized"


# ---------- Error handling ----------


class TestErrorHandling:
    def test_401_raises_trello_api_error(self, client: TrelloClient) -> None:
        client._http.request.return_value = _error_response(401, "Unauthorized")

        with pytest.raises(TrelloAPIError, match="Trello API error 401: Unauthorized") as exc_info:
            client.get("/boards")
        assert exc_info.value.status_code == 401
        assert exc_info.value.text == "Unauthorized"

    def test_404_raises_trello_api_error(self, client: TrelloClient) -> None:
        client._http.request.return_value = _error_response(404, "Not Found")

        with pytest.raises(TrelloAPIError) as exc_info:
            client.get("/cards/nonexistent")
        assert exc_info.value.status_code == 404

    def test_500_raises_trello_api_error(self, client: TrelloClient) -> None:
        client._http.request.return_value = _error_response(500, "Internal Server Error")

        with pytest.raises(TrelloAPIError) as exc_info:
            client.post("/cards")
        assert exc_info.value.status_code == 500

    def test_success_returns_json(self, client: TrelloClient) -> None:
        client._http.request.return_value = _ok_response({"id": "abc", "name": "Board"})

        result = client.get("/boards/abc")
        assert result == {"id": "abc", "name": "Board"}

    def test_post_error_includes_body(self, client: TrelloClient) -> None:
        client._http.request.return_value = _error_response(400, "invalid value for name")

        with pytest.raises(TrelloAPIError, match="invalid value for name"):
            client.post("/cards", params={"name": ""})

    def test_put_error(self, client: TrelloClient) -> None:
        client._http.request.return_value = _error_response(403, "Forbidden")

        with pytest.raises(TrelloAPIError, match="Trello API error 403"):
            client.put("/boards/b1", params={"name": "x"})

    def test_delete_error(self, client: TrelloClient) -> None:
        client._http.request.return_value = _error_response(404, "Not Found")

        with pytest.raises(TrelloAPIError):
            client.delete("/cards/missing")

    def test_error_still_caught_as_runtime_error(self, client: TrelloClient) -> None:
        """Backward compat: existing code catching RuntimeError still works."""
        client._http.request.return_value = _error_response(500, "Server Error")

        with pytest.raises(RuntimeError, match="Trello API error 500"):
            client.get("/boards")


# ---------- Reactive rate limiting (429 Retry-After) ----------


class TestReactiveRateLimiting:
    def test_429_retries_with_retry_after_header(self, client: TrelloClient) -> None:
        """429 with Retry-After: 2 should sleep 2s and retry."""
        resp_429 = _error_response(429, "Rate limit exceeded")
        resp_429.headers = {"Retry-After": "2"}
        resp_ok = _ok_response({"id": "b1"})

        client._http.request.side_effect = [resp_429, resp_ok]

        with patch("server.lib.client.time.sleep") as mock_sleep:
            result = client.get("/boards/b1")

        mock_sleep.assert_called_once_with(2)
        assert result == {"id": "b1"}
        assert client._http.request.call_count == 2

    def test_429_retries_with_default_backoff(self, client: TrelloClient) -> None:
        """429 without Retry-After header should sleep 5s (default)."""
        resp_429 = _error_response(429, "Rate limit exceeded")
        resp_429.headers = {}
        resp_ok = _ok_response({"id": "b1"})

        client._http.request.side_effect = [resp_429, resp_ok]

        with patch("server.lib.client.time.sleep") as mock_sleep:
            result = client.get("/boards/b1")

        mock_sleep.assert_called_once_with(5)
        assert result == {"id": "b1"}

    def test_429_exhausts_retries(self, client: TrelloClient) -> None:
        """3 consecutive 429s should raise RuntimeError."""
        resp_429 = _error_response(429, "Rate limit exceeded")
        resp_429.headers = {"Retry-After": "1"}

        client._http.request.side_effect = [resp_429, resp_429, resp_429, resp_429]

        with patch("server.lib.client.time.sleep"), pytest.raises(RuntimeError, match="429"):
            client.get("/boards/b1")

        # 1 initial + 3 retries = 4 attempts
        assert client._http.request.call_count == 4

    def test_non_429_error_not_retried(self, client: TrelloClient) -> None:
        """Non-429 errors should raise immediately without retry."""
        resp_500 = _error_response(500, "Internal Server Error")

        client._http.request.side_effect = [resp_500]

        with (
            patch("server.lib.client.time.sleep") as mock_sleep,
            pytest.raises(RuntimeError, match="500"),
        ):
            client.get("/boards/b1")

        mock_sleep.assert_not_called()
        assert client._http.request.call_count == 1

    def test_429_invalid_retry_after_uses_default(self, client: TrelloClient) -> None:
        """429 with non-numeric Retry-After should use default 5s."""
        resp_429 = _error_response(429, "Rate limit exceeded")
        resp_429.headers = {"Retry-After": "invalid"}
        resp_ok = _ok_response({"id": "b1"})

        client._http.request.side_effect = [resp_429, resp_ok]

        with patch("server.lib.client.time.sleep") as mock_sleep:
            client.get("/boards/b1")

        mock_sleep.assert_called_once_with(5)


# ---------- Singleton get_client ----------


class TestGetClient:
    def test_get_client_returns_trello_client(self, mocker: pytest.MockerFixture) -> None:
        import server.lib.client as client_mod

        client_mod._cached_client = None
        mocker.patch(
            "server.lib.client.load_config",
            return_value=TrelloConfig(api_key="k", token="t"),
        )
        mocker.patch("httpx.Client")
        try:
            c = get_client()
            assert isinstance(c, TrelloClient)
        finally:
            client_mod._cached_client = None

    def test_get_client_caches_instance(self, mocker: pytest.MockerFixture) -> None:
        import server.lib.client as client_mod

        client_mod._cached_client = None
        mocker.patch(
            "server.lib.client.load_config",
            return_value=TrelloConfig(api_key="k", token="t"),
        )
        mocker.patch("httpx.Client")
        try:
            c1 = get_client()
            c2 = get_client()
            assert c1 is c2
        finally:
            client_mod._cached_client = None


# ---------- HTTP timeout ----------


class TestHttpTimeout:
    def test_client_passes_config_timeout_to_httpx(self) -> None:
        cfg = TrelloConfig(api_key="k", token="t")
        with patch("httpx.Client") as mock_httpx:
            TrelloClient(cfg)
        mock_httpx.assert_called_once()
        _, kwargs = mock_httpx.call_args
        assert kwargs["timeout"] == 30

    def test_client_passes_custom_timeout_to_httpx(self) -> None:
        cfg = TrelloConfig(api_key="k", token="t", http_timeout=60)
        with patch("httpx.Client") as mock_httpx:
            TrelloClient(cfg)
        mock_httpx.assert_called_once()
        _, kwargs = mock_httpx.call_args
        assert kwargs["timeout"] == 60

    def test_get_client_uses_configured_timeout(self, mocker: pytest.MockerFixture) -> None:
        import server.lib.client as client_mod

        client_mod._cached_client = None
        mocker.patch(
            "server.lib.client.load_config",
            return_value=TrelloConfig(api_key="k", token="t", http_timeout=45),
        )
        mock_httpx = mocker.patch("httpx.Client")
        try:
            get_client()
            _, kwargs = mock_httpx.call_args
            assert kwargs["timeout"] == 45
        finally:
            client_mod._cached_client = None
