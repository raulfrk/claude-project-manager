from __future__ import annotations

import dataclasses
import logging

import pytest

from server.lib.models import ProjectMeta, Todo
from server.tools.todos import (
    ParentLinks,
    _parent_id_from_tag,
    _resolve_parent_for_hooks,
    _todo_hook_fields,
)


def _meta() -> ProjectMeta:
    """Minimal ProjectMeta for hook-field tests."""
    return ProjectMeta(name="demo")


def _todo(id_: str, **kwargs) -> Todo:
    """Build a Todo with `id` + `title` + caller-provided overrides.

    Delegates all defaulting to `Todo` itself; tests override only what they care about.
    """
    return Todo(id=id_, title=f"todo {id_}", **kwargs)


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


def test_resolve_returns_empty_when_no_parent_marker():
    child = _todo("2", tags=[])
    parents = [_todo("1", todoist_task_id="tid")]
    result = _resolve_parent_for_hooks(child, [*parents, child])
    assert result == ParentLinks()


def test_resolve_uses_group_tag():
    # Flat model: parent resolved exclusively via group:<id> tag
    parent = _todo("1", todoist_task_id="FROM-TAG")
    child = _todo("2", tags=["group:1"])
    result = _resolve_parent_for_hooks(child, [parent, child])
    assert result.todoist_task_id == "FROM-TAG"


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


def test_hook_fields_flat_child_injects_todoist_id():
    parent = _todo("1", todoist_task_id="PAR-T")
    child = _todo("2", tags=["group:1"])
    fields = _todo_hook_fields(
        child,
        _meta(),
        name="demo",
        todos=[parent, child],
    )
    assert fields["parent_todoist_task_id"] == "PAR-T"


def test_hook_fields_flat_child_injects_jira_key():
    parent = _todo("1", jira_issue_key="CPM-100")
    child = _todo("2", tags=["group:1"])
    fields = _todo_hook_fields(
        child,
        _meta(),
        name="demo",
        todos=[parent, child],
    )
    assert fields["parent_jira_issue_key"] == "CPM-100"


def test_hook_fields_flat_child_injects_trello_card_id():
    parent = _todo("1", trello_card_id="CARD-1")
    child = _todo("2", tags=["group:1"])
    fields = _todo_hook_fields(
        child,
        _meta(),
        name="demo",
        todos=[parent, child],
    )
    assert fields["parent_trello_card_id"] == "CARD-1"


def test_hook_fields_flat_child_injects_trello_checklist_id():
    parent = _todo("1", trello_checklist_id="CL-1")
    child = _todo("2", tags=["group:1"])
    fields = _todo_hook_fields(
        child,
        _meta(),
        name="demo",
        todos=[parent, child],
    )
    assert fields["parent_trello_checklist_id"] == "CL-1"


def test_hook_fields_top_level_has_no_parent_fields():
    todo = _todo("1")
    fields = _todo_hook_fields(todo, _meta(), name="demo", todos=[todo])
    assert "parent_todoist_task_id" not in fields
    assert "parent_jira_issue_key" not in fields
    assert "parent_trello_card_id" not in fields
    assert "parent_trello_checklist_id" not in fields
