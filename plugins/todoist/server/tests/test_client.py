"""Tests for TodoistClient: HTTP methods, error handling, convenience methods, singleton."""

from __future__ import annotations

import httpx
import pytest

import server.lib.client as client_mod
from server.lib.client import TodoistClient, get_client
from server.lib.config import TodoistConfig

_PROXY_VARS = (
    "ALL_PROXY", "all_proxy", "HTTP_PROXY", "http_proxy",
    "HTTPS_PROXY", "https_proxy", "FTP_PROXY", "ftp_proxy",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Reset cached client and clear proxy env vars that break httpx.Client()."""
    client_mod._cached_client = None
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)
    yield  # type: ignore[misc]
    client_mod._cached_client = None


def _make_client(api_token: str = "tok-test") -> TodoistClient:
    return TodoistClient(TodoistConfig(api_token=api_token))


class TestGet:
    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_request(
            method: str, path: str, **kwargs: object
        ) -> httpx.Response:
            assert method == "GET"
            assert path == "/tasks"
            return httpx.Response(200, json=[{"id": "1"}])

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)
        result = client.get("/tasks", params={"project_id": "123"})
        assert result == [{"id": "1"}]

    def test_with_params(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, object] = {}

        def mock_request(
            method: str, path: str, **kwargs: object
        ) -> httpx.Response:
            captured.update(kwargs)
            return httpx.Response(200, json={"ok": True})

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)
        client.get("/projects", params={"limit": "50"})
        assert captured["params"] == {"limit": "50"}


class TestPost:
    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_request(
            method: str, path: str, **kwargs: object
        ) -> httpx.Response:
            assert method == "POST"
            assert path == "/tasks"
            return httpx.Response(200, json={"id": "99", "content": "Buy milk"})

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)
        result = client.post("/tasks", json={"content": "Buy milk"})
        assert result["id"] == "99"


class TestDelete:
    def test_success_empty_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_request(
            method: str, path: str, **kwargs: object
        ) -> httpx.Response:
            assert method == "DELETE"
            return httpx.Response(204)

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)
        result = client.delete("/tasks/42")
        assert result == {"ok": True}


class TestError401:
    def test_invalid_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_request(
            method: str, path: str, **kwargs: object
        ) -> httpx.Response:
            return httpx.Response(401, text="Unauthorized")

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)
        with pytest.raises(RuntimeError, match="Invalid API token"):
            client.get("/tasks")


class TestError429:
    def test_rate_limit_with_retry_after(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def mock_request(
            method: str, path: str, **kwargs: object
        ) -> httpx.Response:
            return httpx.Response(
                429, text="Too Many Requests", headers={"Retry-After": "30"}
            )

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)
        with pytest.raises(RuntimeError, match="Retry after 30 seconds"):
            client.get("/tasks")

    def test_rate_limit_no_retry_after_header(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def mock_request(
            method: str, path: str, **kwargs: object
        ) -> httpx.Response:
            return httpx.Response(429, text="Too Many Requests")

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)
        with pytest.raises(RuntimeError, match="Retry after 60 seconds"):
            client.get("/tasks")


class TestTimeout:
    def test_timeout_exception(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_request(
            method: str, path: str, **kwargs: object
        ) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)
        with pytest.raises(RuntimeError, match="request timed out"):
            client.get("/tasks")


class TestOtherErrors:
    def test_500_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_request(
            method: str, path: str, **kwargs: object
        ) -> httpx.Response:
            return httpx.Response(500, text="Internal Server Error")

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)
        with pytest.raises(RuntimeError, match="Todoist API error 500"):
            client.get("/tasks")

    def test_404_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_request(
            method: str, path: str, **kwargs: object
        ) -> httpx.Response:
            return httpx.Response(404, text="Not Found")

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)
        with pytest.raises(RuntimeError, match="Todoist API error 404: Not Found"):
            client.post("/tasks/999")


class TestCloseTask:
    def test_close_calls_correct_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        def mock_request(
            method: str, path: str, **kwargs: object
        ) -> httpx.Response:
            captured["method"] = method
            captured["path"] = path
            return httpx.Response(204)

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)
        result = client.close_task("abc-123")
        assert captured["method"] == "POST"
        assert captured["path"] == "/tasks/abc-123/close"
        assert result == {"ok": True}


class TestReopenTask:
    def test_reopen_calls_correct_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict[str, object] = {}

        def mock_request(
            method: str, path: str, **kwargs: object
        ) -> httpx.Response:
            captured["method"] = method
            captured["path"] = path
            return httpx.Response(204)

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)
        result = client.reopen_task("abc-456")
        assert captured["method"] == "POST"
        assert captured["path"] == "/tasks/abc-456/reopen"
        assert result == {"ok": True}


class TestSingleton:
    def test_get_client_returns_same_instance(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "server.lib.client.load_config",
            lambda: TodoistConfig(api_token="tok-singleton"),
        )
        c1 = get_client()
        c2 = get_client()
        assert c1 is c2

    def test_get_client_uses_load_config(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "server.lib.client.load_config",
            lambda: TodoistConfig(api_token="tok-from-config"),
        )
        client = get_client()
        assert client._config.api_token == "tok-from-config"


class TestAuthHeader:
    def test_bearer_token_in_headers(self) -> None:
        client = _make_client(api_token="my-secret-token")
        assert client._http.headers["authorization"] == "Bearer my-secret-token"
