"""Tests for code quality fixes 475.41-475.44, 475.88."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

import server.lib.client as client_mod
from server.lib.client import TodoistClient
from server.lib.config import TodoistConfig
from server.lib.models import local_to_todoist_priority, todoist_to_local_priority
from server.tools.tasks import _resolve_priority

_PROXY_VARS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "FTP_PROXY",
    "ftp_proxy",
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    client_mod._cached_client = None
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)


def _make_client(api_token: str = "tok-test") -> TodoistClient:
    return TodoistClient(TodoistConfig(api_token=api_token))


def _api_task(
    id: str = "1",
    content: str = "Task",
    priority: int = 1,
    **extra: Any,
) -> dict[str, Any]:
    return {"id": id, "content": content, "priority": priority, **extra}


# -- 475.41: Specific exceptions in batch ops --------------------------------


class TestBatchSpecificExceptions:
    """Batch ops catch transient vs permanent errors separately."""

    @pytest.fixture()
    def mock_client(self, monkeypatch: pytest.MonkeyPatch) -> MagicMock:
        client = MagicMock(spec=TodoistClient)
        monkeypatch.setattr("server.tools.tasks.get_client", lambda: client)
        return client

    def _get_tool(self, name: str) -> Any:
        from mcp.server.fastmcp import FastMCP

        from server.tools.tasks import register

        app = FastMCP("test")
        register(app)
        return app._tool_manager._tools[name]

    def test_add_tasks_timeout_marked_transient(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = httpx.TimeoutException("timed out")
        tool = self._get_tool("todoist_add_tasks")
        result = json.loads(tool.fn(tasks=[{"content": "X"}]))

        assert len(result["failures"]) == 1
        assert "transient" in result["failures"][0]["error"]

    def test_add_tasks_connect_error_marked_transient(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = httpx.ConnectError("connection refused")
        tool = self._get_tool("todoist_add_tasks")
        result = json.loads(tool.fn(tasks=[{"content": "X"}]))

        assert len(result["failures"]) == 1
        assert "transient" in result["failures"][0]["error"]

    def test_add_tasks_runtime_error_not_transient(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = RuntimeError("API error 400")
        tool = self._get_tool("todoist_add_tasks")
        result = json.loads(tool.fn(tasks=[{"content": "X"}]))

        assert len(result["failures"]) == 1
        assert "transient" not in result["failures"][0]["error"]

    def test_complete_tasks_timeout_marked_transient(self, mock_client: MagicMock) -> None:
        mock_client.close_task.side_effect = httpx.TimeoutException("timed out")
        tool = self._get_tool("todoist_complete_tasks")
        result = json.loads(tool.fn(ids=["t1"]))

        assert len(result["failures"]) == 1
        assert "transient" in result["failures"][0]["error"]

    def test_update_tasks_connect_error_marked_transient(self, mock_client: MagicMock) -> None:
        mock_client.post.side_effect = httpx.ConnectError("refused")
        tool = self._get_tool("todoist_update_tasks")
        result = json.loads(tool.fn(tasks=[{"id": "1", "content": "X"}]))

        assert len(result["failures"]) == 1
        assert "transient" in result["failures"][0]["error"]

    def test_uncomplete_tasks_timeout_marked_transient(self, mock_client: MagicMock) -> None:
        mock_client.reopen_task.side_effect = httpx.TimeoutException("timed out")
        tool = self._get_tool("todoist_uncomplete_tasks")
        result = json.loads(tool.fn(ids=["t1"]))

        assert len(result["failures"]) == 1
        assert "transient" in result["failures"][0]["error"]


# -- 475.42: Cache resp.json() in init ----------------------------------------


class TestInitCachedJson:
    """todoist_init parses resp.json() once and caches the result."""

    def test_non_json_response_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(*args: Any, **kwargs: Any) -> httpx.Response:
            return httpx.Response(200, content=b"not json", headers={"content-type": "text/plain"})

        monkeypatch.setattr(httpx, "get", mock_get)

        from mcp.server.fastmcp import FastMCP

        from server.tools.init import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_init"]
        result = json.loads(tool.fn(api_token="tok-test"))

        assert "error" in result
        assert "not valid JSON" in result["error"]

    def test_non_dict_response_returns_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(*args: Any, **kwargs: Any) -> httpx.Response:
            return httpx.Response(200, json=["not", "a", "dict"])

        monkeypatch.setattr(httpx, "get", mock_get)

        from mcp.server.fastmcp import FastMCP

        from server.tools.init import register

        app = FastMCP("test")
        register(app)
        tool = app._tool_manager._tools["todoist_init"]
        result = json.loads(tool.fn(api_token="tok-test"))

        assert "error" in result
        assert "not valid JSON" in result["error"]


# -- 475.43: Consistent priority defaults ------------------------------------


class TestConsistentPriorityDefaults:
    """Unknown values map to medium consistently."""

    def test_resolve_priority_unknown_string_returns_medium(self) -> None:
        # Unknown string → 3 (Todoist p3 = medium), not 1 (highest)
        assert _resolve_priority("garbage") == 3

    def test_resolve_priority_unknown_empty_returns_medium(self) -> None:
        assert _resolve_priority("") == 3

    def test_local_to_todoist_unknown_returns_p4(self) -> None:
        # local_to_todoist defaults to p4 (low) — documenting existing behavior
        assert local_to_todoist_priority("garbage") == "p4"

    def test_todoist_to_local_unknown_int_returns_low(self) -> None:
        # todoist_to_local defaults to low — documenting existing behavior
        assert todoist_to_local_priority(99) == "low"

    def test_todoist_to_local_unknown_string_returns_low(self) -> None:
        assert todoist_to_local_priority("p99") == "low"


# -- 475.44: Preserve exception chain (from e) --------------------------------


class TestExceptionChainPreserved:
    """raise ... from e preserves the original exception cause."""

    def test_timeout_preserves_cause(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original = httpx.TimeoutException("original timeout")

        def mock_request(*args: Any, **kwargs: Any) -> httpx.Response:
            raise original

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)

        with pytest.raises(RuntimeError) as exc_info:
            client.get("/tasks")

        assert exc_info.value.__cause__ is original

    def test_connect_error_preserves_cause(self, monkeypatch: pytest.MonkeyPatch) -> None:
        original = httpx.ConnectError("connection refused")

        def mock_request(*args: Any, **kwargs: Any) -> httpx.Response:
            raise original

        client = _make_client()
        monkeypatch.setattr(client._http, "request", mock_request)

        with pytest.raises(RuntimeError) as exc_info:
            client.get("/tasks")

        assert exc_info.value.__cause__ is original


# -- 475.88: Protect resp.json() against JSONDecodeError ----------------------


class TestJsonDecodeProtection:
    """_handle_response raises descriptive error on non-JSON body."""

    def test_non_json_success_body_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client()
        resp = httpx.Response(
            200,
            content=b"<html>not json</html>",
            headers={"content-type": "text/html"},
        )

        with pytest.raises(RuntimeError, match="non-JSON response") as exc_info:
            client._handle_response(resp)

        assert "status 200" in str(exc_info.value)
        assert "<html>" in str(exc_info.value)

    def test_valid_json_success_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client()
        resp = httpx.Response(200, json={"id": "1"})
        result = client._handle_response(resp)
        assert result == {"id": "1"}

    def test_empty_success_body_returns_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = _make_client()
        resp = httpx.Response(204)
        result = client._handle_response(resp)
        assert result == {"ok": True}
