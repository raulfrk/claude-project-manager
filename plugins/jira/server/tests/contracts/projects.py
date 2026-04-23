"""Endpoint contracts for Jira project, component, version, sprint, and metadata tools.

Covers: jira_list_projects, jira_get_project, jira_get_components,
jira_create_component, jira_get_versions, jira_create_version,
jira_get_sprints, jira_move_to_sprint, jira_get_issue_types,
jira_get_fields, jira_get_priorities, jira_get_statuses,
jira_get_labels, jira_search_users, jira_get_link_types,
jira_link_issues, jira_get_transitions, jira_transition_issue,
jira_get_watchers, jira_add_watcher, jira_remove_watcher,
jira_get_worklogs, jira_add_worklog, jira_delete_worklog,
jira_add_comment, jira_update_comment, jira_delete_comment,
jira_add_attachment, jira_list_attachments, jira_delete_attachment.

Contracts are built from the vendored OpenAPI spec at
``openapi/jira-dc-v2.json``.
"""

from __future__ import annotations

from test_contracts.openapi import endpoint_contract

from tests.contracts import _SPEC_PATH

_BEARER_HEADERS = {"Authorization": "Bearer {token}"}
_ATTACHMENT_HEADERS = {**_BEARER_HEADERS, "X-Atlassian-Token": "no-check"}


def _c(
    method: str,
    url: str,
    status: str | int = "2xx",
    headers: dict[str, str] | None = None,
):
    return endpoint_contract(
        _SPEC_PATH,
        method,
        url,
        required_headers=headers or _BEARER_HEADERS,
        auth_style="bearer",
        status=status,
    )


# --- Projects ---

LIST_PROJECTS = _c("GET", "/rest/api/2/project")
GET_PROJECT = _c("GET", "/rest/api/2/project/{projectKey}")

# --- Components ---

GET_COMPONENTS = _c("GET", "/rest/api/2/project/{projectKey}/components")
CREATE_COMPONENT = _c("POST", "/rest/api/2/component")

# --- Versions ---

GET_VERSIONS = _c("GET", "/rest/api/2/project/{projectKey}/versions")
CREATE_VERSION = _c("POST", "/rest/api/2/version")

# --- Sprints (Agile API) ---

GET_SPRINTS = _c("GET", "/rest/agile/1.0/board/{boardId}/sprint")
MOVE_TO_SPRINT = _c("POST", "/rest/agile/1.0/sprint/{sprintId}/issue", status=204)

# --- Metadata ---

GET_ISSUE_TYPES = _c("GET", "/rest/api/2/issuetype")
GET_FIELDS = _c("GET", "/rest/api/2/field")
GET_PRIORITIES = _c("GET", "/rest/api/2/priority")
GET_STATUSES = _c("GET", "/rest/api/2/status")

# --- Labels ---

GET_LABELS = _c("GET", "/rest/api/2/label")

# --- Users ---

SEARCH_USERS = _c("GET", "/rest/api/2/user/search")

# --- Links ---

LINK_ISSUES = _c("POST", "/rest/api/2/issueLink", status=201)
GET_LINK_TYPES = _c("GET", "/rest/api/2/issueLinkType")

# --- Transitions ---

GET_TRANSITIONS = _c("GET", "/rest/api/2/issue/{issueKey}/transitions")
TRANSITION_ISSUE = _c("POST", "/rest/api/2/issue/{issueKey}/transitions", status=204)

# --- Watchers ---

GET_WATCHERS = _c("GET", "/rest/api/2/issue/{issueKey}/watchers")
ADD_WATCHER = _c("POST", "/rest/api/2/issue/{issueKey}/watchers", status=204)
REMOVE_WATCHER = _c("DELETE", "/rest/api/2/issue/{issueKey}/watchers", status=204)

# --- Worklogs ---

GET_WORKLOGS = _c("GET", "/rest/api/2/issue/{issueKey}/worklog")
ADD_WORKLOG = _c("POST", "/rest/api/2/issue/{issueKey}/worklog")
DELETE_WORKLOG = _c("DELETE", "/rest/api/2/issue/{issueKey}/worklog/{worklogId}", status=204)

# --- Comments ---

ADD_COMMENT = _c("POST", "/rest/api/2/issue/{issueKey}/comment")
UPDATE_COMMENT = _c("PUT", "/rest/api/2/issue/{issueKey}/comment/{commentId}")
DELETE_COMMENT = _c("DELETE", "/rest/api/2/issue/{issueKey}/comment/{commentId}", status=204)

# --- Attachments ---

ADD_ATTACHMENT = _c(
    "POST",
    "/rest/api/2/issue/{issueKey}/attachments",
    headers=_ATTACHMENT_HEADERS,
)
LIST_ATTACHMENTS = _c("GET", "/rest/api/2/issue/{issueKey}")
DELETE_ATTACHMENT = _c("DELETE", "/rest/api/2/attachment/{attachmentId}", status=204)
