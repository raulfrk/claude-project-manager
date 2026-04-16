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


from server.lib.models import Todo  # noqa: E402
from server.tools.todos import _resolve_parent_for_hooks  # noqa: E402


def _todo(id_: str, **kwargs) -> Todo:
    """Helper: build a minimal Todo with sensible defaults; overridable per test."""
    defaults = {
        "id": id_,
        "title": f"todo {id_}",
        "tags": [],
        "parent": None,
        "children": [],
        "status": "pending",
        "priority": "medium",
        "todoist_task_id": None,
        "trello_card_id": None,
        "trello_checklist_id": None,
        "trello_checklist_item_id": None,
        "jira_issue_key": None,
    }
    defaults.update(kwargs)
    return Todo(**defaults)


def test_resolve_returns_empty_when_no_parent_marker():
    child = _todo("2", tags=[])
    parents = [_todo("1", todoist_task_id="tid")]
    result = _resolve_parent_for_hooks(child, [*parents, child])
    assert result == ParentLinks()


def test_resolve_uses_group_tag_over_parent_field():
    # Both set — tag wins
    parent_via_tag = _todo("1", todoist_task_id="FROM-TAG")
    parent_via_field = _todo("9", todoist_task_id="FROM-FIELD")
    child = _todo("2", tags=["group:1"], parent="9")
    result = _resolve_parent_for_hooks(
        child,
        [parent_via_tag, parent_via_field, child],
    )
    assert result.todoist_task_id == "FROM-TAG"


def test_resolve_falls_back_to_parent_field():
    parent = _todo("9", todoist_task_id="FROM-FIELD")
    child = _todo("2", parent="9")  # no group tag
    result = _resolve_parent_for_hooks(child, [parent, child])
    assert result.todoist_task_id == "FROM-FIELD"


def test_resolve_returns_empty_when_parent_id_unknown():
    child = _todo("2", tags=["group:404"])
    result = _resolve_parent_for_hooks(child, [child])  # no parent in list
    assert result == ParentLinks()


def test_resolve_injects_all_integration_ids():
    parent = _todo(
        "1",
        todoist_task_id="T",
        trello_card_id="R",
        trello_checklist_id="CL",
        jira_issue_key="CPM-1",
    )
    child = _todo("2", tags=["group:1"])
    result = _resolve_parent_for_hooks(child, [parent, child])
    assert result == ParentLinks(
        todoist_task_id="T",
        trello_card_id="R",
        trello_checklist_id="CL",
        jira_issue_key="CPM-1",
    )


def test_resolve_handles_parent_with_no_integrations():
    parent = _todo("1")  # no integration ids
    child = _todo("2", tags=["group:1"])
    result = _resolve_parent_for_hooks(child, [parent, child])
    assert result == ParentLinks()
