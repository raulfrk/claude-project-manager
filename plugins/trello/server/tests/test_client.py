"""Tests for TrelloClient: auth params, rate limiting, error handling."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from server.lib.client import TrelloClient, get_client
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
    def test_auth_params_included_in_get(self, client: TrelloClient) -> None:
        client._http.get.return_value = _ok_response({"id": "b1"})

        client.get("/boards/b1")

        _, kwargs = client._http.get.call_args
        assert kwargs["params"]["key"] == "test-key"
        assert kwargs["params"]["token"] == "test-token"

    def test_auth_params_included_in_post(self, client: TrelloClient) -> None:
        client._http.post.return_value = _ok_response()

        client.post("/cards", params={"name": "c1"})

        _, kwargs = client._http.post.call_args
        params = kwargs["params"]
        assert params["key"] == "test-key"
        assert params["token"] == "test-token"
        assert params["name"] == "c1"

    def test_auth_params_included_in_put(self, client: TrelloClient) -> None:
        client._http.put.return_value = _ok_response()

        client.put("/cards/c1", params={"name": "updated"})

        _, kwargs = client._http.put.call_args
        params = kwargs["params"]
        assert params["key"] == "test-key"
        assert params["token"] == "test-token"
        assert params["name"] == "updated"

    def test_auth_params_included_in_delete(self, client: TrelloClient) -> None:
        client._http.delete.return_value = _ok_response()

        client.delete("/cards/c1")

        _, kwargs = client._http.delete.call_args
        assert kwargs["params"]["key"] == "test-key"
        assert kwargs["params"]["token"] == "test-token"

    def test_params_none_defaults_to_empty(self, client: TrelloClient) -> None:
        client._http.get.return_value = _ok_response([])

        client.get("/boards")

        _, kwargs = client._http.get.call_args
        assert kwargs["params"] == {"key": "test-key", "token": "test-token"}

    def test_post_merges_json_kwarg(self, client: TrelloClient) -> None:
        client._http.post.return_value = _ok_response()

        client.post("/cards", json={"name": "c1"})

        _, kwargs = client._http.post.call_args
        assert kwargs["json"] == {"name": "c1"}

    def test_put_merges_json_kwarg(self, client: TrelloClient) -> None:
        client._http.put.return_value = _ok_response()

        client.put("/cards/c1", json={"name": "updated"})

        _, kwargs = client._http.put.call_args
        assert kwargs["json"] == {"name": "updated"}


# ---------- Rate limiting ----------


class TestRateLimiting:
    def test_no_sleep_under_limit(self) -> None:
        config = TrelloConfig(api_key="k", token="t", rate_limit_per_10s=5)
        with patch("httpx.Client"):
            c = TrelloClient(config)
        c._http = MagicMock()
        c._http.get.return_value = _ok_response()

        with patch("server.lib.client.time.sleep") as mock_sleep:
            for _ in range(4):
                c.get("/boards")
            mock_sleep.assert_not_called()

    def test_sleeps_when_limit_exceeded(self) -> None:
        config = TrelloConfig(api_key="k", token="t", rate_limit_per_10s=2)
        with patch("httpx.Client"):
            c = TrelloClient(config)
        c._http = MagicMock()
        c._http.get.return_value = _ok_response()

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
        c._http.get.return_value = _ok_response()
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
        c._http.get.return_value = _ok_response()

        assert len(c._request_timestamps) == 0
        c.get("/a")
        assert len(c._request_timestamps) == 1
        c.get("/b")
        assert len(c._request_timestamps) == 2


# ---------- Error handling ----------


class TestErrorHandling:
    def test_401_raises_runtime_error(self, client: TrelloClient) -> None:
        client._http.get.return_value = _error_response(401, "Unauthorized")

        with pytest.raises(RuntimeError, match="Trello API error 401: Unauthorized"):
            client.get("/boards")

    def test_404_raises_runtime_error(self, client: TrelloClient) -> None:
        client._http.get.return_value = _error_response(404, "Not Found")

        with pytest.raises(RuntimeError, match="Trello API error 404"):
            client.get("/cards/nonexistent")

    def test_500_raises_runtime_error(self, client: TrelloClient) -> None:
        client._http.post.return_value = _error_response(500, "Internal Server Error")

        with pytest.raises(RuntimeError, match="Trello API error 500"):
            client.post("/cards")

    def test_success_returns_json(self, client: TrelloClient) -> None:
        client._http.get.return_value = _ok_response({"id": "abc", "name": "Board"})

        result = client.get("/boards/abc")
        assert result == {"id": "abc", "name": "Board"}

    def test_post_error_includes_body(self, client: TrelloClient) -> None:
        client._http.post.return_value = _error_response(400, "invalid value for name")

        with pytest.raises(RuntimeError, match="invalid value for name"):
            client.post("/cards", params={"name": ""})

    def test_put_error(self, client: TrelloClient) -> None:
        client._http.put.return_value = _error_response(403, "Forbidden")

        with pytest.raises(RuntimeError, match="Trello API error 403"):
            client.put("/boards/b1", params={"name": "x"})

    def test_delete_error(self, client: TrelloClient) -> None:
        client._http.delete.return_value = _error_response(404, "Not Found")

        with pytest.raises(RuntimeError, match="Trello API error 404"):
            client.delete("/cards/missing")


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
