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
"""

from __future__ import annotations

from test_contracts.base import EndpointContract

_BEARER_HEADERS = {"Authorization": "Bearer {token}"}

# --- Projects ---

LIST_PROJECTS = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/project",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={"items": {"properties": {"key": {"type": "string"}}}},
    response_status=200,
)

GET_PROJECT = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/project/{projectKey}",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={
        "properties": {
            "key": {"type": "string"},
            "name": {"type": "string"},
        }
    },
    response_status=200,
)

# --- Components ---

GET_COMPONENTS = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/project/{projectKey}/components",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={"items": {"properties": {"name": {"type": "string"}}}},
    response_status=200,
)

CREATE_COMPONENT = EndpointContract(
    method="POST",
    url_pattern="/rest/api/2/component",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema={
        "properties": {
            "project": {"type": "string"},
            "name": {"type": "string"},
        }
    },
    response_schema={
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
        }
    },
    response_status=201,
)

# --- Versions ---

GET_VERSIONS = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/project/{projectKey}/versions",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={"items": {"properties": {"name": {"type": "string"}}}},
    response_status=200,
)

CREATE_VERSION = EndpointContract(
    method="POST",
    url_pattern="/rest/api/2/version",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema={
        "properties": {
            "project": {"type": "string"},
            "name": {"type": "string"},
        }
    },
    response_schema={
        "properties": {
            "id": {"type": "string"},
            "name": {"type": "string"},
        }
    },
    response_status=201,
)

# --- Sprints (Agile API) ---

GET_SPRINTS = EndpointContract(
    method="GET",
    url_pattern="/rest/agile/1.0/board/{boardId}/sprint",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={
        "properties": {
            "values": {"type": "array"},
        }
    },
    response_status=200,
)

MOVE_TO_SPRINT = EndpointContract(
    method="POST",
    url_pattern="/rest/agile/1.0/sprint/{sprintId}/issue",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema={
        "properties": {
            "issues": {"type": "array"},
        }
    },
    response_schema={},
    response_status=204,
)

# --- Metadata ---

GET_ISSUE_TYPES = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/issuetype",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={"items": {"properties": {"name": {"type": "string"}}}},
    response_status=200,
)

GET_FIELDS = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/field",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={"items": {"properties": {"id": {"type": "string"}}}},
    response_status=200,
)

GET_PRIORITIES = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/priority",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={"items": {"properties": {"name": {"type": "string"}}}},
    response_status=200,
)

GET_STATUSES = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/status",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={"items": {"properties": {"name": {"type": "string"}}}},
    response_status=200,
)

# --- Labels ---

GET_LABELS = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/label",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={
        "properties": {
            "values": {"type": "array"},
        }
    },
    response_status=200,
)

# --- Users ---

SEARCH_USERS = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/user/search",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={"items": {"properties": {"name": {"type": "string"}}}},
    response_status=200,
)

# --- Links ---

LINK_ISSUES = EndpointContract(
    method="POST",
    url_pattern="/rest/api/2/issueLink",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema={
        "properties": {
            "type": {"type": "object"},
            "inwardIssue": {"type": "object"},
            "outwardIssue": {"type": "object"},
        }
    },
    response_schema={},
    response_status=201,
)

GET_LINK_TYPES = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/issueLinkType",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={
        "properties": {
            "issueLinkTypes": {"type": "array"},
        }
    },
    response_status=200,
)

# --- Transitions ---

GET_TRANSITIONS = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/issue/{issueKey}/transitions",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={
        "properties": {
            "transitions": {"type": "array"},
        }
    },
    response_status=200,
)

TRANSITION_ISSUE = EndpointContract(
    method="POST",
    url_pattern="/rest/api/2/issue/{issueKey}/transitions",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema={
        "properties": {
            "transition": {"type": "object"},
        }
    },
    response_schema={},
    response_status=204,
)

# --- Watchers ---

GET_WATCHERS = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/issue/{issueKey}/watchers",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={
        "properties": {
            "watchCount": {"type": "integer"},
            "watchers": {"type": "array"},
        }
    },
    response_status=200,
)

ADD_WATCHER = EndpointContract(
    method="POST",
    url_pattern="/rest/api/2/issue/{issueKey}/watchers",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,  # Body is a plain JSON string, not object
    response_schema={},
    response_status=204,
)

REMOVE_WATCHER = EndpointContract(
    method="DELETE",
    url_pattern="/rest/api/2/issue/{issueKey}/watchers",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={},
    response_status=204,
)

# --- Worklogs ---

GET_WORKLOGS = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/issue/{issueKey}/worklog",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={
        "properties": {
            "worklogs": {"type": "array"},
            "total": {"type": "integer"},
        }
    },
    response_status=200,
)

ADD_WORKLOG = EndpointContract(
    method="POST",
    url_pattern="/rest/api/2/issue/{issueKey}/worklog",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema={
        "properties": {
            "timeSpent": {"type": "string"},
        }
    },
    response_schema={
        "properties": {
            "id": {"type": "string"},
            "timeSpent": {"type": "string"},
        }
    },
    response_status=201,
)

DELETE_WORKLOG = EndpointContract(
    method="DELETE",
    url_pattern="/rest/api/2/issue/{issueKey}/worklog/{worklogId}",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={},
    response_status=204,
)

# --- Comments ---

ADD_COMMENT = EndpointContract(
    method="POST",
    url_pattern="/rest/api/2/issue/{issueKey}/comment",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema={
        "properties": {
            "body": {"type": "string"},
        }
    },
    response_schema={
        "properties": {
            "id": {"type": "string"},
            "body": {"type": "string"},
        }
    },
    response_status=201,
)

UPDATE_COMMENT = EndpointContract(
    method="PUT",
    url_pattern="/rest/api/2/issue/{issueKey}/comment/{commentId}",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema={
        "properties": {
            "body": {"type": "string"},
        }
    },
    response_schema={
        "properties": {
            "id": {"type": "string"},
            "body": {"type": "string"},
        }
    },
    response_status=200,
)

DELETE_COMMENT = EndpointContract(
    method="DELETE",
    url_pattern="/rest/api/2/issue/{issueKey}/comment/{commentId}",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={},
    response_status=204,
)

# --- Attachments ---

ADD_ATTACHMENT = EndpointContract(
    method="POST",
    url_pattern="/rest/api/2/issue/{issueKey}/attachments",
    required_headers={**_BEARER_HEADERS, "X-Atlassian-Token": "no-check"},
    auth_style="bearer",
    request_schema=None,  # multipart, not JSON
    response_schema={"items": {"properties": {"id": {"type": "string"}}}},
    response_status=200,
)

LIST_ATTACHMENTS = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/issue/{issueKey}",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={
        "properties": {
            "fields": {
                "type": "object",
                "properties": {
                    "attachment": {"type": "array"},
                },
            }
        }
    },
    response_status=200,
)

DELETE_ATTACHMENT = EndpointContract(
    method="DELETE",
    url_pattern="/rest/api/2/attachment/{attachmentId}",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={},
    response_status=204,
)
