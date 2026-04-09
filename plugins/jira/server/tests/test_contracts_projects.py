"""Contract tests for Jira project and auxiliary tools.

Validates that every non-issue tool sends correct HTTP requests
(method, URL, auth, body) and parses responses according to the contract.
Uses respx to intercept httpx traffic from a real JiraClient.

Covers: jira_list_projects, jira_get_project, jira_get_components,
jira_create_component, jira_get_versions, jira_create_version,
jira_get_sprints, jira_move_to_sprint, jira_get_issue_types,
jira_get_fields, jira_get_priorities, jira_get_statuses,
jira_get_labels, jira_search_users, jira_link_issues,
jira_get_link_types, jira_get_transitions, jira_transition_issue,
jira_get_watchers, jira_add_watcher, jira_remove_watcher,
jira_get_worklogs, jira_add_worklog, jira_delete_worklog,
jira_add_comment, jira_update_comment, jira_delete_comment,
jira_list_attachments, jira_delete_attachment.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest
import respx
from test_contracts.builders import build_error_response, build_success_response
from test_contracts.validators import assert_request_matches_contract, assert_response_parses

from server.lib.client import JiraClient
from server.lib.config import JiraConfig
from tests.contracts import errors as err
from tests.contracts import projects as c

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


def _make_tools(module_path: str, client: JiraClient) -> dict[str, Any]:
    """Register tools from a module on a FastMCP with get_client patched."""
    import importlib

    from mcp.server.fastmcp import FastMCP

    mod = importlib.import_module(module_path)
    app = FastMCP("test")
    with patch(f"{module_path}.get_client", return_value=client):
        mod.register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


@pytest.fixture()
def project_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.projects", client)


@pytest.fixture()
def component_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.components", client)


@pytest.fixture()
def version_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.versions", client)


@pytest.fixture()
def sprint_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.sprints", client)


@pytest.fixture()
def metadata_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.metadata", client)


@pytest.fixture()
def label_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.labels", client)


@pytest.fixture()
def user_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.users", client)


@pytest.fixture()
def link_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.links", client)


@pytest.fixture()
def transition_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.transitions", client)


@pytest.fixture()
def watcher_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.watchers", client)


@pytest.fixture()
def worklog_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.worklogs", client)


@pytest.fixture()
def comment_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.comments", client)


@pytest.fixture()
def attachment_tools(client: JiraClient) -> dict[str, Any]:
    return _make_tools("server.tools.attachments", client)


# ===========================================================================
# Projects
# ===========================================================================


class TestListProjectsContract:
    @respx.mock
    def test_request_and_response(self, project_tools: dict, client: JiraClient) -> None:
        response_data = [{"key": "PROJ", "name": "Project One"}, {"key": "DEV", "name": "Dev"}]
        route = respx.get(f"{BASE_URL}/rest/api/2/project").mock(
            return_value=build_success_response(c.LIST_PROJECTS, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.projects.get_client", lambda: client)
            result = project_tools["jira_list_projects"]()

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_PROJECTS)
        parsed = json.loads(result)
        assert len(parsed) == 2

    @respx.mock
    def test_auth_header(self, project_tools: dict, client: JiraClient) -> None:
        respx.get(f"{BASE_URL}/rest/api/2/project").mock(
            return_value=build_success_response(c.LIST_PROJECTS, [{"key": "PROJ", "name": "P"}])
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.projects.get_client", lambda: client)
            project_tools["jira_list_projects"]()

        req = respx.calls[0].request
        assert req.headers["authorization"] == f"Bearer {TOKEN}"


class TestGetProjectContract:
    @respx.mock
    def test_request_and_response(self, project_tools: dict, client: JiraClient) -> None:
        response_data = {"key": "PROJ", "name": "Project One"}
        route = respx.get(f"{BASE_URL}/rest/api/2/project/PROJ").mock(
            return_value=build_success_response(c.GET_PROJECT, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.projects.get_client", lambda: client)
            result = project_tools["jira_get_project"](project_key="PROJ")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_PROJECT, path_params={"projectKey": "PROJ"})
        parsed = json.loads(result)
        assert_response_parses(parsed, c.GET_PROJECT)

    @respx.mock
    def test_not_found(self, project_tools: dict, client: JiraClient) -> None:
        # jira_get_project checks whitelist first; use a whitelisted key with 404 response
        respx.get(f"{BASE_URL}/rest/api/2/project/PROJ").mock(
            return_value=build_error_response(err.NOT_FOUND)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.projects.get_client", lambda: client)
            with pytest.raises(RuntimeError, match="404"):
                project_tools["jira_get_project"](project_key="PROJ")


# ===========================================================================
# Components
# ===========================================================================


class TestGetComponentsContract:
    @respx.mock
    def test_request_and_response(self, component_tools: dict, client: JiraClient) -> None:
        response_data = [{"name": "Backend"}, {"name": "Frontend"}]
        route = respx.get(f"{BASE_URL}/rest/api/2/project/PROJ/components").mock(
            return_value=build_success_response(c.GET_COMPONENTS, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.components.get_client", lambda: client)
            component_tools["jira_get_components"](project_key="PROJ")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_COMPONENTS, path_params={"projectKey": "PROJ"})


class TestCreateComponentContract:
    @respx.mock
    def test_request_and_response(self, component_tools: dict, client: JiraClient) -> None:
        response_data = {"id": "10001", "name": "API"}
        route = respx.post(f"{BASE_URL}/rest/api/2/component").mock(
            return_value=build_success_response(c.CREATE_COMPONENT, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.components.get_client", lambda: client)
            result = component_tools["jira_create_component"](
                project_key="PROJ", name="API", description="API layer"
            )

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.CREATE_COMPONENT)
        parsed = json.loads(result)
        assert_response_parses(parsed, c.CREATE_COMPONENT)


# ===========================================================================
# Versions
# ===========================================================================


class TestGetVersionsContract:
    @respx.mock
    def test_request_and_response(self, version_tools: dict, client: JiraClient) -> None:
        response_data = [{"name": "1.0.0"}, {"name": "2.0.0"}]
        route = respx.get(f"{BASE_URL}/rest/api/2/project/PROJ/versions").mock(
            return_value=build_success_response(c.GET_VERSIONS, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.versions.get_client", lambda: client)
            version_tools["jira_get_versions"](project_key="PROJ")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_VERSIONS, path_params={"projectKey": "PROJ"})


class TestCreateVersionContract:
    @respx.mock
    def test_request_and_response(self, version_tools: dict, client: JiraClient) -> None:
        response_data = {"id": "10010", "name": "3.0.0"}
        route = respx.post(f"{BASE_URL}/rest/api/2/version").mock(
            return_value=build_success_response(c.CREATE_VERSION, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.versions.get_client", lambda: client)
            result = version_tools["jira_create_version"](
                project_key="PROJ", name="3.0.0", description="Major release"
            )

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.CREATE_VERSION)
        parsed = json.loads(result)
        assert_response_parses(parsed, c.CREATE_VERSION)


# ===========================================================================
# Sprints
# ===========================================================================


class TestGetSprintsContract:
    @respx.mock
    def test_request_and_response(self, sprint_tools: dict, client: JiraClient) -> None:
        response_data = {"values": [{"id": 1, "name": "Sprint 1", "state": "active"}]}
        route = respx.get(f"{BASE_URL}/rest/agile/1.0/board/42/sprint").mock(
            return_value=build_success_response(c.GET_SPRINTS, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.sprints.get_client", lambda: client)
            result = sprint_tools["jira_get_sprints"](board_id="42", state="active")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_SPRINTS, path_params={"boardId": "42"})
        parsed = json.loads(result)
        assert_response_parses(parsed, c.GET_SPRINTS)


class TestMoveToSprintContract:
    @respx.mock
    def test_request_and_response(self, sprint_tools: dict, client: JiraClient) -> None:
        route = respx.post(f"{BASE_URL}/rest/agile/1.0/sprint/7/issue").mock(
            return_value=httpx.Response(200, json={})
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.sprints.get_client", lambda: client)
            result = sprint_tools["jira_move_to_sprint"](
                sprint_id="7", issue_keys=["PROJ-1", "PROJ-2"]
            )

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.MOVE_TO_SPRINT, path_params={"sprintId": "7"})
        parsed = json.loads(result)
        assert parsed["ok"] is True


# ===========================================================================
# Metadata
# ===========================================================================


class TestGetIssueTypesContract:
    @respx.mock
    def test_request_and_response(self, metadata_tools: dict, client: JiraClient) -> None:
        response_data = [{"name": "Task"}, {"name": "Bug"}, {"name": "Story"}]
        route = respx.get(f"{BASE_URL}/rest/api/2/issuetype").mock(
            return_value=build_success_response(c.GET_ISSUE_TYPES, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.metadata.get_client", lambda: client)
            metadata_tools["jira_get_issue_types"]()

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_ISSUE_TYPES)


class TestGetFieldsContract:
    @respx.mock
    def test_request_and_response(self, metadata_tools: dict, client: JiraClient) -> None:
        response_data = [{"id": "summary", "name": "Summary"}, {"id": "status", "name": "Status"}]
        route = respx.get(f"{BASE_URL}/rest/api/2/field").mock(
            return_value=build_success_response(c.GET_FIELDS, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.metadata.get_client", lambda: client)
            metadata_tools["jira_get_fields"]()

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_FIELDS)


class TestGetPrioritiesContract:
    @respx.mock
    def test_request_and_response(self, metadata_tools: dict, client: JiraClient) -> None:
        response_data = [{"name": "High"}, {"name": "Medium"}, {"name": "Low"}]
        route = respx.get(f"{BASE_URL}/rest/api/2/priority").mock(
            return_value=build_success_response(c.GET_PRIORITIES, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.metadata.get_client", lambda: client)
            metadata_tools["jira_get_priorities"]()

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_PRIORITIES)


class TestGetStatusesContract:
    @respx.mock
    def test_request_and_response(self, metadata_tools: dict, client: JiraClient) -> None:
        response_data = [{"name": "Open"}, {"name": "In Progress"}, {"name": "Done"}]
        route = respx.get(f"{BASE_URL}/rest/api/2/status").mock(
            return_value=build_success_response(c.GET_STATUSES, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.metadata.get_client", lambda: client)
            metadata_tools["jira_get_statuses"]()

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_STATUSES)


# ===========================================================================
# Labels
# ===========================================================================


class TestGetLabelsContract:
    @respx.mock
    def test_request_and_response(self, label_tools: dict, client: JiraClient) -> None:
        response_data = {"values": ["backend", "frontend", "urgent"]}
        route = respx.get(f"{BASE_URL}/rest/api/2/label").mock(
            return_value=build_success_response(c.GET_LABELS, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.labels.get_client", lambda: client)
            result = label_tools["jira_get_labels"](max_results=100)

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_LABELS)
        parsed = json.loads(result)
        assert_response_parses(parsed, c.GET_LABELS)


# ===========================================================================
# Users
# ===========================================================================


class TestSearchUsersContract:
    @respx.mock
    def test_request_and_response(self, user_tools: dict, client: JiraClient) -> None:
        response_data = [{"name": "alice", "displayName": "Alice"}]
        route = respx.get(f"{BASE_URL}/rest/api/2/user/search").mock(
            return_value=build_success_response(c.SEARCH_USERS, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.users.get_client", lambda: client)
            user_tools["jira_search_users"](query="alice", max_results=10)

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.SEARCH_USERS)


# ===========================================================================
# Links
# ===========================================================================


class TestLinkIssuesContract:
    @respx.mock
    def test_request_and_response(self, link_tools: dict, client: JiraClient) -> None:
        route = respx.post(f"{BASE_URL}/rest/api/2/issueLink").mock(
            return_value=httpx.Response(200, json={})
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.links.get_client", lambda: client)
            result = link_tools["jira_link_issues"](
                inward_key="PROJ-1", outward_key="PROJ-2", link_type="Blocks"
            )

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.LINK_ISSUES)
        parsed = json.loads(result)
        assert parsed["ok"] is True
        assert parsed["link_type"] == "Blocks"


class TestGetLinkTypesContract:
    @respx.mock
    def test_request_and_response(self, link_tools: dict, client: JiraClient) -> None:
        response_data = {
            "issueLinkTypes": [{"name": "Blocks", "inward": "is blocked by", "outward": "blocks"}]
        }
        route = respx.get(f"{BASE_URL}/rest/api/2/issueLinkType").mock(
            return_value=build_success_response(c.GET_LINK_TYPES, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.links.get_client", lambda: client)
            result = link_tools["jira_get_link_types"]()

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_LINK_TYPES)
        parsed = json.loads(result)
        assert_response_parses(parsed, c.GET_LINK_TYPES)


# ===========================================================================
# Transitions
# ===========================================================================


class TestGetTransitionsContract:
    @respx.mock
    def test_request_and_response(self, transition_tools: dict, client: JiraClient) -> None:
        response_data = {"transitions": [{"id": "21", "name": "In Progress"}]}
        route = respx.get(f"{BASE_URL}/rest/api/2/issue/PROJ-1/transitions").mock(
            return_value=build_success_response(c.GET_TRANSITIONS, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.transitions.get_client", lambda: client)
            result = transition_tools["jira_get_transitions"](issue_key="PROJ-1")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_TRANSITIONS, path_params={"issueKey": "PROJ-1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, c.GET_TRANSITIONS)


class TestTransitionIssueContract:
    @respx.mock
    def test_request_and_response(self, transition_tools: dict, client: JiraClient) -> None:
        route = respx.post(f"{BASE_URL}/rest/api/2/issue/PROJ-1/transitions").mock(
            return_value=httpx.Response(200, json={})
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.transitions.get_client", lambda: client)
            result = transition_tools["jira_transition_issue"](
                issue_key="PROJ-1", transition_id="21"
            )

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.TRANSITION_ISSUE, path_params={"issueKey": "PROJ-1"})
        parsed = json.loads(result)
        assert parsed["ok"] is True


# ===========================================================================
# Watchers
# ===========================================================================


class TestGetWatchersContract:
    @respx.mock
    def test_request_and_response(self, watcher_tools: dict, client: JiraClient) -> None:
        response_data = {"watchCount": 2, "watchers": [{"name": "alice"}, {"name": "bob"}]}
        route = respx.get(f"{BASE_URL}/rest/api/2/issue/PROJ-1/watchers").mock(
            return_value=build_success_response(c.GET_WATCHERS, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.watchers.get_client", lambda: client)
            result = watcher_tools["jira_get_watchers"](issue_key="PROJ-1")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_WATCHERS, path_params={"issueKey": "PROJ-1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, c.GET_WATCHERS)


class TestAddWatcherContract:
    @respx.mock
    def test_request_and_response(self, watcher_tools: dict, client: JiraClient) -> None:
        route = respx.post(f"{BASE_URL}/rest/api/2/issue/PROJ-1/watchers").mock(
            return_value=httpx.Response(200, json={})
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.watchers.get_client", lambda: client)
            result = watcher_tools["jira_add_watcher"](issue_key="PROJ-1", username="bob")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.ADD_WATCHER, path_params={"issueKey": "PROJ-1"})
        parsed = json.loads(result)
        assert parsed["ok"] is True


class TestRemoveWatcherContract:
    @respx.mock
    def test_request_and_response(self, watcher_tools: dict, client: JiraClient) -> None:
        route = respx.delete(f"{BASE_URL}/rest/api/2/issue/PROJ-1/watchers").mock(
            return_value=httpx.Response(200, json={})
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.watchers.get_client", lambda: client)
            result = watcher_tools["jira_remove_watcher"](issue_key="PROJ-1", username="bob")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.REMOVE_WATCHER, path_params={"issueKey": "PROJ-1"})
        parsed = json.loads(result)
        assert parsed["deleted"] is True


# ===========================================================================
# Worklogs
# ===========================================================================


class TestGetWorklogsContract:
    @respx.mock
    def test_request_and_response(self, worklog_tools: dict, client: JiraClient) -> None:
        response_data = {
            "worklogs": [{"id": "100", "timeSpent": "2h"}],
            "total": 1,
        }
        route = respx.get(f"{BASE_URL}/rest/api/2/issue/PROJ-1/worklog").mock(
            return_value=build_success_response(c.GET_WORKLOGS, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.worklogs.get_client", lambda: client)
            result = worklog_tools["jira_get_worklogs"](issue_key="PROJ-1")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_WORKLOGS, path_params={"issueKey": "PROJ-1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, c.GET_WORKLOGS)


class TestAddWorklogContract:
    @respx.mock
    def test_request_and_response(self, worklog_tools: dict, client: JiraClient) -> None:
        response_data = {"id": "200", "timeSpent": "3h"}
        route = respx.post(f"{BASE_URL}/rest/api/2/issue/PROJ-1/worklog").mock(
            return_value=build_success_response(c.ADD_WORKLOG, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.worklogs.get_client", lambda: client)
            result = worklog_tools["jira_add_worklog"](
                issue_key="PROJ-1", time_spent="3h", comment="Worked on feature"
            )

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.ADD_WORKLOG, path_params={"issueKey": "PROJ-1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, c.ADD_WORKLOG)


class TestDeleteWorklogContract:
    @respx.mock
    def test_request_and_response(self, worklog_tools: dict, client: JiraClient) -> None:
        route = respx.delete(f"{BASE_URL}/rest/api/2/issue/PROJ-1/worklog/200").mock(
            return_value=httpx.Response(200, json={})
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.worklogs.get_client", lambda: client)
            result = worklog_tools["jira_delete_worklog"](issue_key="PROJ-1", worklog_id="200")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(
            req, c.DELETE_WORKLOG, path_params={"issueKey": "PROJ-1", "worklogId": "200"}
        )
        parsed = json.loads(result)
        assert parsed["deleted"] is True


# ===========================================================================
# Comments
# ===========================================================================


class TestAddCommentContract:
    @respx.mock
    def test_request_and_response(self, comment_tools: dict, client: JiraClient) -> None:
        response_data = {"id": "300", "body": "Great work"}
        route = respx.post(f"{BASE_URL}/rest/api/2/issue/PROJ-1/comment").mock(
            return_value=build_success_response(c.ADD_COMMENT, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.comments.get_client", lambda: client)
            result = comment_tools["jira_add_comment"](issue_key="PROJ-1", body="Great work")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.ADD_COMMENT, path_params={"issueKey": "PROJ-1"})
        parsed = json.loads(result)
        assert_response_parses(parsed, c.ADD_COMMENT)


class TestUpdateCommentContract:
    @respx.mock
    def test_request_and_response(self, comment_tools: dict, client: JiraClient) -> None:
        response_data = {"id": "300", "body": "Updated comment"}
        route = respx.put(f"{BASE_URL}/rest/api/2/issue/PROJ-1/comment/300").mock(
            return_value=build_success_response(c.UPDATE_COMMENT, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.comments.get_client", lambda: client)
            result = comment_tools["jira_update_comment"](
                issue_key="PROJ-1", comment_id="300", body="Updated comment"
            )

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(
            req, c.UPDATE_COMMENT, path_params={"issueKey": "PROJ-1", "commentId": "300"}
        )
        parsed = json.loads(result)
        assert_response_parses(parsed, c.UPDATE_COMMENT)


class TestDeleteCommentContract:
    @respx.mock
    def test_request_and_response(self, comment_tools: dict, client: JiraClient) -> None:
        route = respx.delete(f"{BASE_URL}/rest/api/2/issue/PROJ-1/comment/300").mock(
            return_value=httpx.Response(200, json={})
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.comments.get_client", lambda: client)
            result = comment_tools["jira_delete_comment"](issue_key="PROJ-1", comment_id="300")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(
            req, c.DELETE_COMMENT, path_params={"issueKey": "PROJ-1", "commentId": "300"}
        )
        parsed = json.loads(result)
        assert parsed["deleted"] is True


# ===========================================================================
# Attachments
# ===========================================================================


class TestListAttachmentsContract:
    @respx.mock
    def test_request_and_response(self, attachment_tools: dict, client: JiraClient) -> None:
        response_data = {
            "fields": {
                "attachment": [{"id": "500", "filename": "report.pdf"}],
            }
        }
        route = respx.get(f"{BASE_URL}/rest/api/2/issue/PROJ-1").mock(
            return_value=build_success_response(c.LIST_ATTACHMENTS, response_data)
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.attachments.get_client", lambda: client)
            result = attachment_tools["jira_list_attachments"](issue_key="PROJ-1")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_ATTACHMENTS)
        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["filename"] == "report.pdf"


class TestDeleteAttachmentContract:
    @respx.mock
    def test_request_and_response(self, attachment_tools: dict, client: JiraClient) -> None:
        route = respx.delete(f"{BASE_URL}/rest/api/2/attachment/500").mock(
            return_value=httpx.Response(200, json={})
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("server.tools.attachments.get_client", lambda: client)
            result = attachment_tools["jira_delete_attachment"](attachment_id="500")

        assert route.called
        req = route.calls[0].request
        assert_request_matches_contract(
            req, c.DELETE_ATTACHMENT, path_params={"attachmentId": "500"}
        )
        parsed = json.loads(result)
        assert parsed["deleted"] is True


# ===========================================================================
# Error contracts (cross-cutting)
# ===========================================================================


class TestErrorContracts:
    """Validate that standard Jira error codes raise RuntimeError through the client."""

    @respx.mock
    def test_unauthorized(self, client: JiraClient) -> None:
        respx.get(f"{BASE_URL}/rest/api/2/issue/X-1").mock(
            return_value=build_error_response(err.UNAUTHORIZED)
        )
        with pytest.raises(RuntimeError, match="401"):
            client.get("/rest/api/2/issue/X-1")

    @respx.mock
    def test_forbidden(self, client: JiraClient) -> None:
        respx.get(f"{BASE_URL}/rest/api/2/issue/X-1").mock(
            return_value=build_error_response(err.FORBIDDEN)
        )
        with pytest.raises(RuntimeError, match="403"):
            client.get("/rest/api/2/issue/X-1")

    @respx.mock
    def test_not_found(self, client: JiraClient) -> None:
        respx.get(f"{BASE_URL}/rest/api/2/issue/X-1").mock(
            return_value=build_error_response(err.NOT_FOUND)
        )
        with pytest.raises(RuntimeError, match="404"):
            client.get("/rest/api/2/issue/X-1")

    @respx.mock
    def test_rate_limited(self, client: JiraClient) -> None:
        respx.get(f"{BASE_URL}/rest/api/2/issue/X-1").mock(
            return_value=build_error_response(err.RATE_LIMITED)
        )
        with pytest.raises(RuntimeError, match="429"):
            client.get("/rest/api/2/issue/X-1")

    @respx.mock
    def test_server_error(self, client: JiraClient) -> None:
        respx.get(f"{BASE_URL}/rest/api/2/issue/X-1").mock(
            return_value=build_error_response(err.SERVER_ERROR)
        )
        with pytest.raises(RuntimeError, match="500"):
            client.get("/rest/api/2/issue/X-1")

    @respx.mock
    def test_bad_request(self, client: JiraClient) -> None:
        respx.post(f"{BASE_URL}/rest/api/2/issue").mock(
            return_value=build_error_response(err.BAD_REQUEST)
        )
        with pytest.raises(RuntimeError, match="400"):
            client.post("/rest/api/2/issue", json_body={"fields": {}})
