"""Tests for jira_update_issue_fields wrapper + shared helpers."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest
from mcp.server.fastmcp import FastMCP

from server.tools.issues import FIELD_MAP, _build_updates_json, register


class TestFieldMap:
    def test_summary_passthrough(self) -> None:
        assert FIELD_MAP["summary"]("Hello") == "Hello"

    def test_description_passthrough(self) -> None:
        assert FIELD_MAP["description"]("Body text") == "Body text"

    def test_priority_wrapped(self) -> None:
        assert FIELD_MAP["priority"]("High") == {"name": "High"}

    def test_labels_passthrough(self) -> None:
        assert FIELD_MAP["labels"](["a", "b"]) == ["a", "b"]

    def test_resolution_wrapped(self) -> None:
        assert FIELD_MAP["resolution"]("Done") == {"name": "Done"}


class TestBuildUpdatesJson:
    def test_single_item_all_fields(self) -> None:
        out = _build_updates_json(
            [
                {
                    "key": "PROJ-1",
                    "summary": "S",
                    "description": "D",
                    "priority": "High",
                    "labels": ["x"],
                    "resolution": "Done",
                }
            ]
        )
        parsed = json.loads(out)
        assert parsed == {
            "updates": [
                {
                    "key": "PROJ-1",
                    "fields": {
                        "summary": "S",
                        "description": "D",
                        "priority": {"name": "High"},
                        "labels": ["x"],
                        "resolution": {"name": "Done"},
                    },
                }
            ]
        }

    def test_none_fields_omitted(self) -> None:
        out = _build_updates_json(
            [{"key": "PROJ-1", "summary": "S", "description": None, "priority": None}]
        )
        parsed = json.loads(out)
        assert parsed["updates"][0]["fields"] == {"summary": "S"}

    def test_multiple_items(self) -> None:
        out = _build_updates_json(
            [
                {"key": "PROJ-1", "resolution": "Done"},
                {"key": "PROJ-2", "summary": "X"},
            ]
        )
        parsed = json.loads(out)
        assert len(parsed["updates"]) == 2
        assert parsed["updates"][0]["fields"] == {"resolution": {"name": "Done"}}
        assert parsed["updates"][1]["fields"] == {"summary": "X"}

    def test_unknown_field_ignored(self) -> None:
        # Forward-compat: unknown keys are silently dropped rather than passed through.
        out = _build_updates_json([{"key": "PROJ-1", "summary": "S", "bogus": "x"}])
        parsed = json.loads(out)
        assert parsed["updates"][0]["fields"] == {"summary": "S"}

    def test_empty_list_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            _build_updates_json([])

    def test_missing_key_raises(self) -> None:
        with pytest.raises(ValueError, match="key"):
            _build_updates_json([{"summary": "S"}])


@pytest.fixture()
def issue_tools(mock_jira_client: MagicMock) -> dict:
    app = FastMCP("test")
    register(app)
    return {name: tool.fn for name, tool in app._tool_manager._tools.items()}


class TestJiraUpdateIssueFields:
    def test_all_fields(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        mock_jira_client.put.return_value = None
        result = issue_tools["jira_update_issue_fields"](
            key="PROJ-1",
            summary="S",
            description="D",
            priority="High",
            labels=["bug"],
        )
        parsed = json.loads(result)
        assert parsed["successes"] == [{"key": "PROJ-1", "status": "updated"}]
        mock_jira_client.put.assert_called_once_with(
            "/rest/api/2/issue/PROJ-1",
            json_body={
                "fields": {
                    "summary": "S",
                    "description": "D",
                    "priority": {"name": "High"},
                    "labels": ["bug"],
                }
            },
        )

    def test_only_resolution(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        mock_jira_client.put.return_value = None
        result = issue_tools["jira_update_issue_fields"](key="PROJ-1", resolution="Done")
        parsed = json.loads(result)
        assert parsed["successes"] == [{"key": "PROJ-1", "status": "updated"}]
        mock_jira_client.put.assert_called_once_with(
            "/rest/api/2/issue/PROJ-1",
            json_body={"fields": {"resolution": {"name": "Done"}}},
        )

    def test_empty_key_returns_error(self, mock_jira_client: MagicMock, issue_tools: dict) -> None:
        result = issue_tools["jira_update_issue_fields"](key="", summary="S")
        parsed = json.loads(result)
        assert parsed == {"error": "key required", "key": ""}
        mock_jira_client.put.assert_not_called()

    def test_all_fields_none_returns_warning(
        self, mock_jira_client: MagicMock, issue_tools: dict
    ) -> None:
        result = issue_tools["jira_update_issue_fields"](key="PROJ-1")
        parsed = json.loads(result)
        assert parsed == {"warning": "no fields to update", "key": "PROJ-1"}
        mock_jira_client.put.assert_not_called()
