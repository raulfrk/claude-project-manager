"""Dedicated error response contract tests for Jira REST API.

Tests each error code (401, 403, 404, 429, 500) against multiple endpoints
(GET /rest/api/3/issue/{key} and POST /rest/api/3/issue) for broader coverage
than the inline error tests in test_contracts_issues.py.

Note: Jira API paths use /rest/api/2 in this codebase (matching the client).
"""

from __future__ import annotations

import json

import pytest
import respx
from test_contracts.builders import build_error_response

from server.lib.client import JiraClient
from server.lib.config import JiraConfig
from tests.contracts import errors as err

BASE_URL = "https://jira.example.com"
TOKEN = "test-pat-token"


@pytest.fixture()
def config() -> JiraConfig:
    return JiraConfig(
        personal_access_token=TOKEN,
        base_url=BASE_URL,
        allowed_project_keys=["PROJ", "DEV"],
        default_user="alice",
    )


@pytest.fixture()
def client(config: JiraConfig, monkeypatch: pytest.MonkeyPatch) -> JiraClient:
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    return JiraClient(config)


@pytest.fixture()
def issue_tools(client: JiraClient) -> dict[str, object]:
    """Register issue tools on a FastMCP with get_client patched to our real client."""
    from unittest.mock import patch

    from mcp.server.fastmcp import FastMCP

    from server.tools.issues import register

    app = FastMCP("test")
    with patch("server.tools.issues.get_client", return_value=client):
        register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


# ---------------------------------------------------------------------------
# 401 Unauthorized — multiple endpoints
# ---------------------------------------------------------------------------


class TestUnauthorized401:
    @respx.mock
    def test_get_issue_401(self, issue_tools: dict, client: JiraClient) -> None:
        """GET /rest/api/2/issue/{key} returns 401."""
        respx.get(f"{BASE_URL}/rest/api/2/issue/PROJ-1").mock(
            return_value=build_error_response(err.UNAUTHORIZED)
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            with pytest.raises(RuntimeError, match="401"):
                issue_tools["jira_get_issue"](issue_key="PROJ-1")

    @respx.mock
    def test_post_issue_401(self, issue_tools: dict, client: JiraClient) -> None:
        """POST /rest/api/2/issue returns 401."""
        respx.post(f"{BASE_URL}/rest/api/2/issue").mock(
            return_value=build_error_response(err.UNAUTHORIZED)
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_create_issue"](project_key="PROJ", summary="Test")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "401" in parsed["error"]


# ---------------------------------------------------------------------------
# 403 Forbidden — multiple endpoints
# ---------------------------------------------------------------------------


class TestForbidden403:
    @respx.mock
    def test_get_issue_403(self, issue_tools: dict, client: JiraClient) -> None:
        """GET /rest/api/2/issue/{key} returns 403."""
        respx.get(f"{BASE_URL}/rest/api/2/issue/PROJ-1").mock(
            return_value=build_error_response(err.FORBIDDEN)
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            with pytest.raises(RuntimeError, match="403"):
                issue_tools["jira_get_issue"](issue_key="PROJ-1")

    @respx.mock
    def test_post_issue_403(self, issue_tools: dict, client: JiraClient) -> None:
        """POST /rest/api/2/issue returns 403."""
        respx.post(f"{BASE_URL}/rest/api/2/issue").mock(
            return_value=build_error_response(err.FORBIDDEN)
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_create_issue"](project_key="PROJ", summary="Test")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "403" in parsed["error"]


# ---------------------------------------------------------------------------
# 404 Not Found — multiple endpoints
# ---------------------------------------------------------------------------


class TestNotFound404:
    @respx.mock
    def test_get_issue_404(self, issue_tools: dict, client: JiraClient) -> None:
        """GET /rest/api/2/issue/{key} returns 404."""
        respx.get(f"{BASE_URL}/rest/api/2/issue/NOPE-1").mock(
            return_value=build_error_response(err.NOT_FOUND)
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            with pytest.raises(RuntimeError, match="404"):
                issue_tools["jira_get_issue"](issue_key="NOPE-1")

    @respx.mock
    def test_post_issue_404(self, issue_tools: dict, client: JiraClient) -> None:
        """POST /rest/api/2/issue returns 404."""
        respx.post(f"{BASE_URL}/rest/api/2/issue").mock(
            return_value=build_error_response(err.NOT_FOUND)
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_create_issue"](project_key="PROJ", summary="Test")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "404" in parsed["error"]


# ---------------------------------------------------------------------------
# 429 Rate Limited — multiple endpoints
# ---------------------------------------------------------------------------


class TestRateLimited429:
    @respx.mock
    def test_get_issue_429(self, issue_tools: dict, client: JiraClient) -> None:
        """GET /rest/api/2/issue/{key} returns 429 with Retry-After header."""
        respx.get(f"{BASE_URL}/rest/api/2/issue/PROJ-1").mock(
            return_value=build_error_response(err.RATE_LIMITED)
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            with pytest.raises(RuntimeError, match="429"):
                issue_tools["jira_get_issue"](issue_key="PROJ-1")

    @respx.mock
    def test_post_issue_429(self, issue_tools: dict, client: JiraClient) -> None:
        """POST /rest/api/2/issue returns 429."""
        respx.post(f"{BASE_URL}/rest/api/2/issue").mock(
            return_value=build_error_response(err.RATE_LIMITED)
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_create_issue"](project_key="PROJ", summary="Test")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "429" in parsed["error"]

    @respx.mock
    def test_429_message_includes_rate_limit_info(self, client: JiraClient) -> None:
        """429 error message should include rate limit details at the client level."""
        respx.get(f"{BASE_URL}/rest/api/2/issue/X-1").mock(
            return_value=build_error_response(err.RATE_LIMITED)
        )
        with pytest.raises(RuntimeError, match="Rate limit exceeded"):
            client.get("/rest/api/2/issue/X-1")


# ---------------------------------------------------------------------------
# 500 Server Error — multiple endpoints
# ---------------------------------------------------------------------------


class TestServerError500:
    @respx.mock
    def test_get_issue_500(self, issue_tools: dict, client: JiraClient) -> None:
        """GET /rest/api/2/issue/{key} returns 500."""
        respx.get(f"{BASE_URL}/rest/api/2/issue/PROJ-1").mock(
            return_value=build_error_response(err.SERVER_ERROR)
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            with pytest.raises(RuntimeError, match="500"):
                issue_tools["jira_get_issue"](issue_key="PROJ-1")

    @respx.mock
    def test_post_issue_500(self, issue_tools: dict, client: JiraClient) -> None:
        """POST /rest/api/2/issue returns 500."""
        respx.post(f"{BASE_URL}/rest/api/2/issue").mock(
            return_value=build_error_response(err.SERVER_ERROR)
        )
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_create_issue"](project_key="PROJ", summary="Test")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "500" in parsed["error"]
