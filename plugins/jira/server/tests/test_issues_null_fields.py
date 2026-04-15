"""Bug #5: null field stripping in jira_update_issues.

${tags} in hook template resolves to '' when None, making malformed JSON upstream.
jira_update_issues strips null-valued fields before PUT so hook templates with
`"labels": ${tags}` don't fail or clear Jira labels when tags is absent.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from server.tools.issues import register


@pytest.fixture()
def issue_tools(mock_jira_client: MagicMock) -> dict:
    """Register issue tools on a mock FastMCP and collect them."""
    from mcp.server.fastmcp import FastMCP

    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraUpdateIssuesNullFieldStripping:
    """jira_update_issues must strip null-valued fields before PUT."""

    def test_null_labels_field_stripped_not_sent(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        """null labels field stripped before PUT; only non-null fields sent."""
        mock_jira_client.put.return_value = None

        payload = json.dumps(
            {"updates": [{"key": "PROJ-1", "fields": {"summary": "Updated title", "labels": None}}]}
        )

        result = issue_tools["jira_update_issues"](updates_json=payload)

        parsed = json.loads(result)
        assert len(parsed["successes"]) == 1
        assert len(parsed["failures"]) == 0
        sent_fields = mock_jira_client.put.call_args[1]["json_body"]["fields"]
        assert "labels" not in sent_fields
        assert sent_fields["summary"] == "Updated title"

    def test_all_null_fields_stripped_becomes_no_fields_failure(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        """All-null fields after stripping treated as 'no fields to update'."""
        payload = json.dumps(
            {"updates": [{"key": "PROJ-1", "fields": {"labels": None, "description": None}}]}
        )

        result = issue_tools["jira_update_issues"](updates_json=payload)

        parsed = json.loads(result)
        assert len(parsed["failures"]) == 1
        assert "No fields" in parsed["failures"][0]["error"]
        mock_jira_client.put.assert_not_called()

    def test_mixed_null_and_valid_fields_sends_only_valid(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        """Null fields stripped; non-null fields sent normally."""
        mock_jira_client.put.return_value = None

        payload = json.dumps(
            {
                "updates": [
                    {
                        "key": "PROJ-2",
                        "fields": {
                            "summary": "Keep me",
                            "labels": None,
                            "description": None,
                            "priority": {"name": "High"},
                        },
                    }
                ]
            }
        )

        result = issue_tools["jira_update_issues"](updates_json=payload)

        parsed = json.loads(result)
        assert len(parsed["successes"]) == 1
        sent_fields = mock_jira_client.put.call_args[1]["json_body"]["fields"]
        assert set(sent_fields.keys()) == {"summary", "priority"}

    def test_hook_template_null_tags_handled_end_to_end(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        """Root-cause simulation: router template resolves tags=None to null in fields dict.

        The router sets labels=null when tags is absent. jira_update_issues strips it
        so the Jira API call succeeds without sending labels (rather than clearing them).
        """
        mock_jira_client.put.return_value = None

        payload = json.dumps(
            {
                "updates": [
                    {
                        "key": "PROJ-1",
                        "fields": {
                            "summary": "My title",
                            "description": "Some notes",
                            "priority": {"name": "Medium"},
                            "labels": None,
                        },
                    }
                ]
            }
        )

        result = issue_tools["jira_update_issues"](updates_json=payload)

        parsed = json.loads(result)
        assert len(parsed["successes"]) == 1, f"Expected success: {parsed}"
        assert len(parsed["failures"]) == 0
        sent_fields = mock_jira_client.put.call_args[1]["json_body"]["fields"]
        assert "labels" not in sent_fields
        assert sent_fields["summary"] == "My title"
        assert sent_fields["priority"] == {"name": "Medium"}
