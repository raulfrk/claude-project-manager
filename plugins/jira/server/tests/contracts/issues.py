"""Endpoint contracts for Jira issue tools.

Covers: jira_search, jira_get_issue, jira_get_issue_comments,
jira_get_epic_issues, jira_get_user_issues, jira_create_issue,
jira_bulk_create_issues, jira_update_issues.
"""

from __future__ import annotations

from test_contracts.base import EndpointContract

_BEARER_HEADERS = {"Authorization": "Bearer {token}"}

SEARCH = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/search",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={
        "properties": {
            "issues": {"type": "array"},
            "total": {"type": "integer"},
        }
    },
    response_status=200,
)

GET_ISSUE = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/issue/{issueKey}",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={
        "properties": {
            "key": {"type": "string"},
            "fields": {"type": "object"},
        }
    },
    response_status=200,
)

GET_ISSUE_COMMENTS = EndpointContract(
    method="GET",
    url_pattern="/rest/api/2/issue/{issueKey}/comment",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema=None,
    response_schema={
        "properties": {
            "comments": {"type": "array"},
            "total": {"type": "integer"},
        }
    },
    response_status=200,
)

# jira_get_epic_issues reuses /rest/api/2/search
EPIC_ISSUES = SEARCH

# jira_get_user_issues reuses /rest/api/2/search
USER_ISSUES = SEARCH

CREATE_ISSUE = EndpointContract(
    method="POST",
    url_pattern="/rest/api/2/issue",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema={
        "properties": {
            "fields": {
                "type": "object",
                "properties": {
                    "project": {"type": "object"},
                    "summary": {"type": "string"},
                    "issuetype": {"type": "object"},
                },
            }
        }
    },
    response_schema={
        "properties": {
            "key": {"type": "string"},
            "self": {"type": "string"},
        }
    },
    response_status=201,
)

BULK_CREATE = EndpointContract(
    method="POST",
    url_pattern="/rest/api/2/issue/bulk",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema={
        "properties": {
            "issueUpdates": {"type": "array"},
        }
    },
    response_schema={
        "properties": {
            "issues": {"type": "array"},
            "errors": {"type": "array"},
        }
    },
    response_status=201,
)

BULK_UPDATE_SINGLE = EndpointContract(
    method="PUT",
    url_pattern="/rest/api/2/issue/{issueKey}",
    required_headers=_BEARER_HEADERS,
    auth_style="bearer",
    request_schema={
        "properties": {
            "fields": {"type": "object"},
        }
    },
    response_schema={},
    response_status=204,
)
