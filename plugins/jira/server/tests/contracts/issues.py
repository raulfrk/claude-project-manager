"""Endpoint contracts for Jira issue tools.

Covers: jira_search, jira_get_issue, jira_get_issue_comments,
jira_get_epic_issues, jira_get_user_issues, jira_create_issue,
jira_bulk_create_issues, jira_update_issues.

Contracts are pulled from the vendored OpenAPI spec via
``endpoint_contract``. Schemas live in ``openapi/jira-dc-v2.json``.
"""

from __future__ import annotations

from test_contracts.openapi import endpoint_contract

from tests.contracts import _SPEC_PATH

_BEARER_HEADERS = {"Authorization": "Bearer {token}"}


def _c(method: str, url: str, status: str | int = "2xx"):
    return endpoint_contract(
        _SPEC_PATH,
        method,
        url,
        required_headers=_BEARER_HEADERS,
        auth_style="bearer",
        status=status,
    )


SEARCH = _c("GET", "/rest/api/2/search")
GET_ISSUE = _c("GET", "/rest/api/2/issue/{issueKey}")
GET_ISSUE_COMMENTS = _c("GET", "/rest/api/2/issue/{issueKey}/comment")

# jira_get_epic_issues and jira_get_user_issues reuse /rest/api/2/search
EPIC_ISSUES = SEARCH
USER_ISSUES = SEARCH

CREATE_ISSUE = _c("POST", "/rest/api/2/issue")
BULK_CREATE = _c("POST", "/rest/api/2/issue/bulk")

# Bulk update of individual issues maps to single-issue PUT /issue/{key}
BULK_UPDATE_SINGLE = _c("PUT", "/rest/api/2/issue/{issueKey}", status=204)
