"""Tests for Jira issue tools."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.lib.config import JiraConfig
from server.tools.issues import register


@pytest.fixture()
def issue_tools(mock_jira_client: MagicMock) -> dict[str, callable]:
    """Register issue tools on a mock FastMCP and collect them."""
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraSearch:
    def test_passes_jql_and_params(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        search_result = {"issues": [{"key": "PROJ-1"}], "total": 1}
        mock_jira_client.get.return_value = search_result

        result = issue_tools["jira_search"](jql="project = PROJ", max_results=10, start_at=5)

        mock_jira_client.get.assert_called_once_with(
            "/rest/api/2/search",
            params={
                "jql": "project = PROJ",
                "maxResults": 10,
                "startAt": 5,
                "fields": (
                    "summary,description,priority,assignee,labels,"
                    "duedate,status,issuetype,parent,subtasks"
                ),
            },
        )
        assert json.loads(result) == search_result

    def test_uses_default_params(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        mock_jira_client.get.return_value = {"issues": [], "total": 0}

        issue_tools["jira_search"](jql="status = Open")

        _, kwargs = mock_jira_client.get.call_args
        assert kwargs["params"]["maxResults"] == 50
        assert kwargs["params"]["startAt"] == 0


class TestJiraGetIssue:
    def test_fetches_issue_by_key(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        issue_data = {"key": "PROJ-42", "fields": {"summary": "Fix bug"}}
        mock_jira_client.get.return_value = issue_data

        result = issue_tools["jira_get_issue"](issue_key="PROJ-42")

        mock_jira_client.get.assert_called_once_with("/rest/api/2/issue/PROJ-42")
        assert json.loads(result) == issue_data


class TestJiraGetIssueComments:
    def test_fetches_comments_by_issue_key(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        comments_data = {"comments": [{"body": "Looks good"}], "total": 1}
        mock_jira_client.get.return_value = comments_data

        result = issue_tools["jira_get_issue_comments"](issue_key="PROJ-42")

        mock_jira_client.get.assert_called_once_with("/rest/api/2/issue/PROJ-42/comment")
        assert json.loads(result) == comments_data


class TestJiraGetEpicIssues:
    def test_searches_with_parent_jql(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        epic_result = {"issues": [{"key": "PROJ-10"}], "total": 1}
        mock_jira_client.get.return_value = epic_result

        result = issue_tools["jira_get_epic_issues"](epic_key="PROJ-5", max_results=25)

        call_args = mock_jira_client.get.call_args
        assert call_args[0][0] == "/rest/api/2/search"
        params = call_args[1]["params"]
        assert "parent = PROJ-5" in params["jql"]
        assert params["maxResults"] == 25
        assert json.loads(result) == epic_result

    def test_default_max_results(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        mock_jira_client.get.return_value = {"issues": [], "total": 0}

        issue_tools["jira_get_epic_issues"](epic_key="PROJ-5")

        params = mock_jira_client.get.call_args[1]["params"]
        assert params["maxResults"] == 50


class TestJiraGetUserIssues:
    def test_uses_explicit_username_and_project_keys(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client._config = JiraConfig(
            personal_access_token="pat",
            base_url="https://jira.example.com",
            allowed_project_keys=["OTHER"],
            default_user="default_user",
        )
        mock_jira_client.get.return_value = {"issues": [], "total": 0}

        issue_tools["jira_get_user_issues"](
            username="alice", project_keys=["PROJ", "DEV"], max_results=10
        )

        params = mock_jira_client.get.call_args[1]["params"]
        jql = params["jql"]
        assert "assignee = alice" in jql
        assert "project in (PROJ, DEV)" in jql
        assert "status not in (Done, Closed, Resolved)" in jql
        assert params["maxResults"] == 10

    def test_falls_back_to_config_defaults(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client._config = JiraConfig(
            personal_access_token="pat",
            base_url="https://jira.example.com",
            allowed_project_keys=["PROJ", "DEV"],
            default_user="config_user",
        )
        mock_jira_client.get.return_value = {"issues": [], "total": 0}

        issue_tools["jira_get_user_issues"]()

        params = mock_jira_client.get.call_args[1]["params"]
        jql = params["jql"]
        assert "assignee = config_user" in jql
        assert "project in (PROJ, DEV)" in jql

    def test_no_username_returns_error(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client._config = JiraConfig(
            personal_access_token="pat",
            base_url="https://jira.example.com",
            default_user="",
        )

        result = issue_tools["jira_get_user_issues"]()

        parsed = json.loads(result)
        assert "error" in parsed
        assert "No username" in parsed["error"]

    def test_no_project_keys_omits_project_clause(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client._config = JiraConfig(
            personal_access_token="pat",
            base_url="https://jira.example.com",
            allowed_project_keys=[],
            default_user="alice",
        )
        mock_jira_client.get.return_value = {"issues": [], "total": 0}

        issue_tools["jira_get_user_issues"](username="alice")

        params = mock_jira_client.get.call_args[1]["params"]
        jql = params["jql"]
        assert "project in" not in jql


class TestJiraCreateIssue:
    def test_create_issue_minimal(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        mock_jira_client.post.return_value = {
            "key": "PROJ-1",
            "self": "https://jira.example.com/rest/api/2/issue/10001",
        }

        result = issue_tools["jira_create_issue"](project_key="PROJ", summary="New task")

        mock_jira_client.post.assert_called_once_with(
            "/rest/api/2/issue",
            json_body={
                "fields": {
                    "project": {"key": "PROJ"},
                    "summary": "New task",
                    "issuetype": {"name": "Task"},
                }
            },
        )
        parsed = json.loads(result)
        assert parsed == {
            "key": "PROJ-1",
            "self": "https://jira.example.com/rest/api/2/issue/10001",
        }

    def test_create_issue_with_epic_link(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client.post.return_value = {
            "key": "PROJ-2",
            "self": "https://jira.example.com/rest/api/2/issue/10002",
        }

        result = issue_tools["jira_create_issue"](
            project_key="PROJ", summary="Child task", parent_key="PROJ-100"
        )

        call_args = mock_jira_client.post.call_args
        fields = call_args[1]["json_body"]["fields"]
        assert fields["parent"] == {"key": "PROJ-100"}
        parsed = json.loads(result)
        assert parsed["key"] == "PROJ-2"

    def test_create_issue_all_fields(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        mock_jira_client.post.return_value = {
            "key": "PROJ-3",
            "self": "https://jira.example.com/rest/api/2/issue/10003",
        }

        result = issue_tools["jira_create_issue"](
            project_key="PROJ",
            summary="Full issue",
            issue_type="Story",
            description="A detailed description",
            priority="High",
            assignee="alice",
            parent_key="PROJ-50",
            labels="backend, urgent",
            components="API, Core",
        )

        call_args = mock_jira_client.post.call_args
        fields = call_args[1]["json_body"]["fields"]
        assert fields["project"] == {"key": "PROJ"}
        assert fields["summary"] == "Full issue"
        assert fields["issuetype"] == {"name": "Story"}
        assert fields["description"] == "A detailed description"
        assert fields["priority"] == {"name": "High"}
        assert fields["assignee"] == {"name": "alice"}
        assert fields["parent"] == {"key": "PROJ-50"}
        assert fields["labels"] == ["backend", "urgent"]
        assert fields["components"] == [{"name": "API"}, {"name": "Core"}]
        parsed = json.loads(result)
        assert parsed["key"] == "PROJ-3"

    def test_create_issue_api_error(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        mock_jira_client.post.side_effect = RuntimeError("Jira API error 400: bad request")

        result = issue_tools["jira_create_issue"](project_key="PROJ", summary="Will fail")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "400" in parsed["error"]


class TestJiraBulkCreateIssues:
    def test_posts_bulk_payload(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        bulk_response = {
            "issues": [{"id": "10001", "key": "PROJ-100"}],
            "errors": [],
        }
        mock_jira_client.post.return_value = bulk_response

        payload = json.dumps(
            {
                "issueUpdates": [
                    {
                        "fields": {
                            "project": {"key": "PROJ"},
                            "summary": "New issue",
                            "issuetype": {"name": "Task"},
                        }
                    }
                ]
            }
        )

        result = issue_tools["jira_bulk_create_issues"](issues_json=payload)

        mock_jira_client.post.assert_called_once_with(
            "/rest/api/2/issue/bulk",
            json_body={
                "issueUpdates": [
                    {
                        "fields": {
                            "project": {"key": "PROJ"},
                            "summary": "New issue",
                            "issuetype": {"name": "Task"},
                        }
                    }
                ]
            },
        )
        assert json.loads(result) == bulk_response

    def test_invalid_json_returns_error(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_bulk_create_issues"](issues_json="not valid json")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid JSON" in parsed["error"]

    def test_missing_issueUpdates_returns_error(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_bulk_create_issues"](issues_json=json.dumps({"foo": "bar"}))

        parsed = json.loads(result)
        assert "error" in parsed
        assert "issueUpdates" in parsed["error"]


class TestJiraBulkUpdateIssues:
    def test_updates_multiple_issues(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        mock_jira_client.put.return_value = None

        payload = json.dumps(
            {
                "updates": [
                    {"key": "PROJ-1", "fields": {"summary": "Updated 1"}},
                    {"key": "PROJ-2", "fields": {"priority": {"name": "High"}}},
                ]
            }
        )

        result = issue_tools["jira_bulk_update_issues"](updates_json=payload)

        parsed = json.loads(result)
        assert len(parsed["successes"]) == 2
        assert len(parsed["failures"]) == 0
        assert parsed["successes"][0] == {"key": "PROJ-1", "status": "updated"}
        assert parsed["successes"][1] == {"key": "PROJ-2", "status": "updated"}

        calls = mock_jira_client.put.call_args_list
        assert calls[0] == (
            ("/rest/api/2/issue/PROJ-1",),
            {"json_body": {"fields": {"summary": "Updated 1"}}},
        )
        assert calls[1] == (
            ("/rest/api/2/issue/PROJ-2",),
            {"json_body": {"fields": {"priority": {"name": "High"}}}},
        )

    def test_invalid_json_returns_error(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_bulk_update_issues"](updates_json="bad json")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid JSON" in parsed["error"]

    def test_missing_updates_returns_error(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_bulk_update_issues"](updates_json=json.dumps({"foo": "bar"}))

        parsed = json.loads(result)
        assert "error" in parsed
        assert "updates" in parsed["error"]

    def test_missing_key_recorded_as_failure(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        payload = json.dumps(
            {
                "updates": [
                    {"fields": {"summary": "No key"}},
                ]
            }
        )

        result = issue_tools["jira_bulk_update_issues"](updates_json=payload)

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert "Missing 'key'" in parsed["failures"][0]["error"]

    def test_no_fields_recorded_as_failure(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        payload = json.dumps(
            {
                "updates": [
                    {"key": "PROJ-1", "fields": {}},
                ]
            }
        )

        result = issue_tools["jira_bulk_update_issues"](updates_json=payload)

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert "No fields" in parsed["failures"][0]["error"]

    def test_api_error_captured_as_failure(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        mock_jira_client.put.side_effect = [
            RuntimeError("Jira API error 500: server error"),
            None,
        ]

        payload = json.dumps(
            {
                "updates": [
                    {"key": "PROJ-1", "fields": {"summary": "Fails"}},
                    {"key": "PROJ-2", "fields": {"summary": "Works"}},
                ]
            }
        )

        result = issue_tools["jira_bulk_update_issues"](updates_json=payload)

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert "500" in parsed["failures"][0]["error"]
        assert len(parsed["successes"]) == 1
        assert parsed["successes"][0]["key"] == "PROJ-2"

    def test_empty_updates_returns_error(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        payload = json.dumps({"updates": []})

        result = issue_tools["jira_bulk_update_issues"](updates_json=payload)

        parsed = json.loads(result)
        assert "error" in parsed
