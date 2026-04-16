from __future__ import annotations

import dataclasses
import logging

import pytest

from server.tools.todos import (
    ParentLinks,
    _parent_id_from_tag,
)


def test_parent_id_from_tag_finds_group():
    assert _parent_id_from_tag(["x", "group:42", "y"]) == "42"


def test_parent_id_from_tag_returns_none_when_absent():
    assert _parent_id_from_tag(["x", "y"]) is None


def test_parent_id_from_tag_returns_none_when_tags_empty():
    assert _parent_id_from_tag([]) is None


def test_parent_id_from_tag_accepts_dotted_ids():
    assert _parent_id_from_tag(["group:475.17"]) == "475.17"


def test_parent_id_from_tag_rejects_empty_id():
    # `group:` with no id is treated as a normal tag, not a parent pointer
    assert _parent_id_from_tag(["group:"]) is None


def test_parent_id_from_tag_uses_first_when_multiple(caplog: pytest.LogCaptureFixture):
    caplog.set_level(logging.DEBUG, logger="server.tools.todos")
    assert _parent_id_from_tag(["group:1", "group:2"]) == "1"
    assert any("multiple group" in r.message.lower() for r in caplog.records)


def test_parent_links_default_is_all_none():
    pl = ParentLinks()
    assert pl.todoist_task_id is None
    assert pl.trello_card_id is None
    assert pl.trello_checklist_id is None
    assert pl.jira_issue_key is None


def test_parent_links_is_frozen():
    pl = ParentLinks()
    with pytest.raises(dataclasses.FrozenInstanceError):
        pl.todoist_task_id = "x"  # type: ignore[misc]
