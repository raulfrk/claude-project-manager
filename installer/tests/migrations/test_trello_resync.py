# installer/tests/migrations/test_trello_resync.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.integrations.trello import TrelloResync
from installer.migrations.types import PendingProject, TodoRef


@pytest.fixture
def project_with_trello(tmp_path: Path) -> PendingProject:
    root = tmp_path / "demo"
    root.mkdir()
    proj = root / "proj.yaml"
    proj.write_text(
        yaml.safe_dump(
            {
                "name": "demo",
                "sync": {
                    "trello": {
                        "enabled": True,
                        "api_key": "k",
                        "api_token": "t",
                        "board_id": "board123",
                        "list_mappings": {"tasks": "tasks-list-id"},
                    },
                },
            }
        ),
    )
    (root / "todos.yaml").write_text("[]\n")
    return PendingProject(
        name="demo", path=root, proj_yaml_path=proj, current_version=1
    )


def _parent_with_checklist() -> TodoRef:
    return TodoRef(
        id="1",
        title="parent",
        trello_card_id="parent-card",
        trello_checklist_id="cl-1",
    )


def _child_of_checklist(idx: int, item_id: str | None = None) -> TodoRef:
    return TodoRef(
        id=f"1.{idx}",
        title=f"child {idx}",
        parent="1",
        trello_checklist_item_id=item_id,
    )


def test_plan_emits_promote_action_per_checklist_item(project_with_trello) -> None:
    migrated = [
        _parent_with_checklist(),
        _child_of_checklist(1, "item-1"),
        _child_of_checklist(2, "item-2"),
    ]
    actions = TrelloResync().plan(project_with_trello, migrated)
    assert len(actions) == 2
    assert all(a.kind == "promote_checklist_item" for a in actions)
    assert {a.target_id for a in actions} == {"item-1", "item-2"}


def test_plan_skips_child_missing_item_id(project_with_trello, caplog) -> None:
    migrated = [
        _parent_with_checklist(),
        _child_of_checklist(1, None),
    ]
    actions = TrelloResync().plan(project_with_trello, migrated)
    assert actions == []
    assert any("missing trello_checklist_item_id" in r.message for r in caplog.records)


@respx.mock
def test_execute_happy_path(project_with_trello) -> None:
    migrated = [
        _parent_with_checklist(),
        _child_of_checklist(1, "item-1"),
    ]
    actions = TrelloResync().plan(project_with_trello, migrated)
    # Order-insensitive mocks for each endpoint used:
    respx.post("https://api.trello.com/1/cards").mock(
        return_value=Response(200, json={"id": "new-card-1"}),
    )
    respx.get(url__regex=r"https://api.trello.com/1/cards/parent-card/.*").mock(
        return_value=Response(200, json=[]),  # parent labels fetch
    )
    respx.delete(
        url__regex=r"https://api.trello.com/1/checklists/cl-1/checkItems/item-1"
    ).mock(
        return_value=Response(200),
    )
    respx.delete(url__regex=r"https://api.trello.com/1/checklists/cl-1").mock(
        return_value=Response(200),
    )

    result = TrelloResync().execute(project_with_trello, actions)
    assert not result.failed
    assert len(result.ok) == 1


@respx.mock
def test_execute_card_create_failure_logged(project_with_trello) -> None:
    migrated = [_parent_with_checklist(), _child_of_checklist(1, "item-1")]
    actions = TrelloResync().plan(project_with_trello, migrated)
    respx.post("https://api.trello.com/1/cards").mock(return_value=Response(500))
    result = TrelloResync().execute(project_with_trello, actions)
    assert len(result.failed) == 1
    assert result.failed[0].retryable is True
