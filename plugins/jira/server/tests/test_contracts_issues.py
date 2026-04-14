"""Contract tests for Jira issue tools.

Validates that every issue-related tool sends correct HTTP requests
(method, URL, auth, body) and parses responses according to the contract.
Uses respx to intercept httpx traffic from a real JiraClient.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from test_contracts.builders import build_error_response, build_success_response
from test_contracts.validators import assert_request_matches_contract, assert_response_parses

from server.lib.client import JiraClient
from server.lib.config import JiraConfig
from tests.contracts import errors as err
from tests.contracts import issues as c

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
    # Clear proxy env vars so httpx.Client doesn't try SOCKS transport
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
# jira_search
# ---------------------------------------------------------------------------


class TestSearchContract:
    @respx.mock
    def test_request_and_response(self, issue_tools: dict, client: JiraClient) -> None:
        response_data = {"issues": [{"key": "PROJ-1"}], "total": 1}
        route = respx.get(f"{BASE_URL}/rest/api/2/search").mock(
            return_value=build_success_response(c.SEARCH, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_search"](jql="project = PROJ", max_results=10, start_at=0)

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.SEARCH)
        parsed = json.loads(result)
        assert_response_parses(parsed, c.SEARCH)

    @respx.mock
    def test_auth_header(self, issue_tools: dict, client: JiraClient) -> None:
        respx.get(f"{BASE_URL}/rest/api/2/search").mock(
            return_value=build_success_response(c.SEARCH, {"issues": [], "total": 0})
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            issue_tools["jira_search"](jql="status = Open")

        req = respx.calls[0].request
        assert req.headers["authorization"] == f"Bearer {TOKEN}"


# ---------------------------------------------------------------------------
# jira_get_issue
# ---------------------------------------------------------------------------


class TestGetIssueContract:
    @respx.mock
    def test_request_and_response(self, issue_tools: dict, client: JiraClient) -> None:
        response_data = {"key": "PROJ-42", "fields": {"summary": "Fix bug"}}
        route = respx.get(f"{BASE_URL}/rest/api/2/issue/PROJ-42").mock(
            return_value=build_success_response(c.GET_ISSUE, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_get_issue"](issue_key="PROJ-42")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_ISSUE, path_params={"issueKey": "PROJ-42"})
        parsed = json.loads(result)
        assert_response_parses(parsed, c.GET_ISSUE)

    @respx.mock
    def test_not_found_error(self, issue_tools: dict, client: JiraClient) -> None:
        respx.get(f"{BASE_URL}/rest/api/2/issue/NOPE-1").mock(
            return_value=build_error_response(err.NOT_FOUND)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_get_issue"](issue_key="NOPE-1")
        parsed = json.loads(result)
        assert "error" in parsed
        assert "404" in parsed["error"]


# ---------------------------------------------------------------------------
# jira_get_issue_comments
# ---------------------------------------------------------------------------


class TestGetIssueCommentsContract:
    @respx.mock
    def test_request_and_response(self, issue_tools: dict, client: JiraClient) -> None:
        response_data = {"comments": [{"body": "Looks good"}], "total": 1}
        route = respx.get(f"{BASE_URL}/rest/api/2/issue/PROJ-42/comment").mock(
            return_value=build_success_response(c.GET_ISSUE_COMMENTS, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_get_issue_comments"](issue_key="PROJ-42")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(
            req, c.GET_ISSUE_COMMENTS, path_params={"issueKey": "PROJ-42"}
        )
        parsed = json.loads(result)
        assert_response_parses(parsed, c.GET_ISSUE_COMMENTS)


# ---------------------------------------------------------------------------
# jira_get_epic_issues
# ---------------------------------------------------------------------------


class TestGetEpicIssuesContract:
    @respx.mock
    def test_request_and_response(self, issue_tools: dict, client: JiraClient) -> None:
        response_data = {"issues": [{"key": "PROJ-10"}], "total": 1}
        route = respx.get(f"{BASE_URL}/rest/api/2/search").mock(
            return_value=build_success_response(c.EPIC_ISSUES, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_get_epic_issues"](epic_key="PROJ-5", page_size=25)

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.EPIC_ISSUES)
        # Verify JQL contains parent reference
        assert "parent+%3D+PROJ-5" in str(req.url) or "parent = PROJ-5" in str(req.url)
        parsed = json.loads(result)
        assert_response_parses(parsed, c.EPIC_ISSUES)


# ---------------------------------------------------------------------------
# jira_get_user_issues
# ---------------------------------------------------------------------------


class TestGetUserIssuesContract:
    @respx.mock
    def test_request_and_response(self, issue_tools: dict, client: JiraClient) -> None:
        response_data = {"issues": [{"key": "PROJ-7"}], "total": 1}
        route = respx.get(f"{BASE_URL}/rest/api/2/search").mock(
            return_value=build_success_response(c.USER_ISSUES, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_get_user_issues"](username="alice", page_size=10)

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.USER_ISSUES)
        parsed = json.loads(result)
        assert_response_parses(parsed, c.USER_ISSUES)


# ---------------------------------------------------------------------------
# jira_create_issue
# ---------------------------------------------------------------------------


class TestCreateIssueContract:
    @respx.mock
    def test_request_and_response(self, issue_tools: dict, client: JiraClient) -> None:
        response_data = {
            "key": "PROJ-99",
            "self": f"{BASE_URL}/rest/api/2/issue/10099",
        }
        route = respx.post(f"{BASE_URL}/rest/api/2/issue").mock(
            return_value=build_success_response(c.CREATE_ISSUE, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_create_issue"](project_key="PROJ", summary="New task")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.CREATE_ISSUE)
        parsed = json.loads(result)
        assert parsed["key"] == "PROJ-99"

    @respx.mock
    def test_bad_request_error(self, issue_tools: dict, client: JiraClient) -> None:
        respx.post(f"{BASE_URL}/rest/api/2/issue").mock(
            return_value=build_error_response(err.BAD_REQUEST)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_create_issue"](project_key="PROJ", summary="Will fail")

        # create_issue catches RuntimeError and returns error JSON
        parsed = json.loads(result)
        assert "error" in parsed
        assert "400" in parsed["error"]

    @respx.mock
    def test_unauthorized_error(self, issue_tools: dict, client: JiraClient) -> None:
        respx.post(f"{BASE_URL}/rest/api/2/issue").mock(
            return_value=build_error_response(err.UNAUTHORIZED)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_create_issue"](project_key="PROJ", summary="No auth")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "401" in parsed["error"]


# ---------------------------------------------------------------------------
# jira_bulk_create_issues
# ---------------------------------------------------------------------------


class TestBulkCreateContract:
    @respx.mock
    def test_request_and_response(self, issue_tools: dict, client: JiraClient) -> None:
        response_data = {
            "issues": [{"id": "10001", "key": "PROJ-100"}],
            "errors": [],
        }
        route = respx.post(f"{BASE_URL}/rest/api/2/issue/bulk").mock(
            return_value=build_success_response(c.BULK_CREATE, response_data)
        )

        payload = json.dumps(
            {
                "issueUpdates": [
                    {
                        "fields": {
                            "project": {"key": "PROJ"},
                            "summary": "Bulk issue",
                            "issuetype": {"name": "Task"},
                        }
                    }
                ]
            }
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_bulk_create_issues"](issues_json=payload)

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.BULK_CREATE)
        parsed = json.loads(result)
        assert_response_parses(parsed, c.BULK_CREATE)

    @respx.mock
    def test_server_error(self, issue_tools: dict, client: JiraClient) -> None:
        respx.post(f"{BASE_URL}/rest/api/2/issue/bulk").mock(
            return_value=build_error_response(err.SERVER_ERROR)
        )

        payload = json.dumps(
            {
                "issueUpdates": [
                    {
                        "fields": {
                            "project": {"key": "PROJ"},
                            "summary": "X",
                            "issuetype": {"name": "Task"},
                        }
                    }
                ]
            }
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_bulk_create_issues"](issues_json=payload)
        parsed = json.loads(result)
        assert "error" in parsed
        assert "500" in parsed["error"]


# ---------------------------------------------------------------------------
# jira_bulk_update_issues
# ---------------------------------------------------------------------------


class TestBulkUpdateContract:
    @respx.mock
    def test_request_and_response(self, issue_tools: dict, client: JiraClient) -> None:
        # bulk_update loops PUT per issue; mock both with JSON body
        # (client always calls resp.json())
        route1 = respx.put(f"{BASE_URL}/rest/api/2/issue/PROJ-1").mock(
            return_value=httpx.Response(200, json={})
        )
        route2 = respx.put(f"{BASE_URL}/rest/api/2/issue/PROJ-2").mock(
            return_value=httpx.Response(200, json={})
        )

        payload = json.dumps(
            {
                "updates": [
                    {"key": "PROJ-1", "fields": {"summary": "Updated 1"}},
                    {"key": "PROJ-2", "fields": {"priority": {"name": "High"}}},
                ]
            }
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_bulk_update_issues"](updates_json=payload)

        assert route1.called
        assert route2.called

        # Validate first PUT request against contract
        req1 = route1.calls[0].request
        assert_request_matches_contract(
            req1, c.BULK_UPDATE_SINGLE, path_params={"issueKey": "PROJ-1"}
        )
        req2 = route2.calls[0].request
        assert_request_matches_contract(
            req2, c.BULK_UPDATE_SINGLE, path_params={"issueKey": "PROJ-2"}
        )

        parsed = json.loads(result)
        assert len(parsed["successes"]) == 2
        assert len(parsed["failures"]) == 0

    @respx.mock
    def test_partial_failure(self, issue_tools: dict, client: JiraClient) -> None:
        respx.put(f"{BASE_URL}/rest/api/2/issue/PROJ-1").mock(
            return_value=build_error_response(err.SERVER_ERROR)
        )
        respx.put(f"{BASE_URL}/rest/api/2/issue/PROJ-2").mock(
            return_value=httpx.Response(200, json={})
        )

        payload = json.dumps(
            {
                "updates": [
                    {"key": "PROJ-1", "fields": {"summary": "Fails"}},
                    {"key": "PROJ-2", "fields": {"summary": "Works"}},
                ]
            }
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_bulk_update_issues"](updates_json=payload)

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert len(parsed["successes"]) == 1

    @respx.mock
    def test_rate_limited_error(self, issue_tools: dict, client: JiraClient) -> None:
        respx.put(f"{BASE_URL}/rest/api/2/issue/PROJ-1").mock(
            return_value=build_error_response(err.RATE_LIMITED)
        )

        payload = json.dumps(
            {"updates": [{"key": "PROJ-1", "fields": {"summary": "Rate limited"}}]}
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.issues.get_client", lambda: client)
            result = issue_tools["jira_bulk_update_issues"](updates_json=payload)

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert "429" in parsed["failures"][0]["error"]
