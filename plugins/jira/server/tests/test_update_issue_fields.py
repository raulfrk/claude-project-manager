"""Tests for jira_update_issue_fields wrapper + shared helpers."""

from __future__ import annotations

import json

import pytest

from server.tools.issues import FIELD_MAP, _build_updates_json


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
