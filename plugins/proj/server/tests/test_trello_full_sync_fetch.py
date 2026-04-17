"""Tests for Bug A fix: _sync_single_project fetches cards (not checklists) for compute_diff.

Spec §6.1 — test_trello_full_sync_fetch.py (4 tests).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from server.lib import storage
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    ProjectTrelloConfig,
    RepoEntry,
    TrelloSync,
)
from server.tools.trello_full_sync import _sync_single_project

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def cfg_with_trello_project(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[ProjConfig, str]:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)

    cfg = ProjConfig(
        tracking_dir=str(tmp_path / "tracking"),
        trello=TrelloSync(enabled=True, default_board_id="board-1"),
    )
    storage.save_config(cfg)

    today = str(date.today())
    proj_dir = Path(cfg.tracking_dir) / "myapp"
    proj_dir.mkdir(parents=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "archive.yaml").write_text("todos: []\n")
    meta = ProjectMeta(
        name="myapp",
        repos=[RepoEntry(label="code", path=str(tmp_path))],
        dates=ProjectDates(created=today, last_updated=today),
        trello_card_id="project-card-1",
        trello=ProjectTrelloConfig(enabled=True, board_id="board-1"),
    )
    storage.save_meta(cfg, meta)
    index = ProjectIndex(
        projects={"myapp": ProjectEntry(name="myapp", tracking_dir=str(proj_dir), created=today)},
    )
    storage.save_index(cfg, index)
    return cfg, "myapp"


def _make_trello_card(card_id: str, name: str, list_id: str, desc: str = "") -> dict:
    return {
        "id": card_id,
        "name": name,
        "desc": desc,
        "idList": list_id,
        "closed": False,
        "idLabels": [],
    }


def _make_trello_list(list_id: str, name: str) -> dict:
    return {"id": list_id, "name": name}


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_sync_single_project_fetches_cards_not_checklists(
    cfg_with_trello_project: tuple[ProjConfig, str],
) -> None:
    """_sync_single_project calls get_cards_by_list_id, NOT get_card_checklists."""
    cfg, name = cfg_with_trello_project

    tasks_list = _make_trello_list("list-tasks", "proj-tasks")
    done_list = _make_trello_list("list-done", "Done")
    projects_list = _make_trello_list("list-proj", "Projects")
    project_card = _make_trello_card("project-card-1", "myapp", "list-proj")

    call_log: list[str] = []

    def mock_call_trello(tool_name: str, params: dict) -> object:
        call_log.append(tool_name)
        if tool_name == "get_lists":
            return [tasks_list, done_list, projects_list]
        if tool_name == "get_cards_by_list_id":
            return []
        if tool_name == "get_card":
            return project_card
        return {}

    with patch("server.tools.trello_full_sync._call_trello_tool", side_effect=mock_call_trello):
        result = _sync_single_project(cfg, name)

    assert "get_card_checklists" not in call_log, (
        "Should NOT call get_card_checklists (old checklist model)"
    )
    assert "get_cards_by_list_id" in call_log, "Should call get_cards_by_list_id (card model)"
    assert "get_lists" in call_log, "Should call get_lists to resolve list IDs"
    assert result.get("status") in ("success", "up_to_date", "partial_success")


def test_compute_diff_receives_populated_cards_list(
    cfg_with_trello_project: tuple[ProjConfig, str],
) -> None:
    """compute_diff is called with a 'cards' key (not 'checklists') in trello_data."""
    cfg, name = cfg_with_trello_project

    from server.lib.ids import next_todo_id
    from server.lib.models import Todo

    # Add a todo with a trello_card_id so compute_diff can see it
    meta = storage.load_meta(cfg, name)
    todo = Todo(
        id=next_todo_id(meta),
        title="My Task",
        trello_card_id="card-task-1",
    )
    storage.save_todos(cfg, name, [todo])
    storage.save_meta(cfg, meta)

    tasks_card = _make_trello_card("card-task-1", "[myapp] [1] My Task", "list-tasks")
    tasks_list = _make_trello_list("list-tasks", "proj-tasks")
    done_list = _make_trello_list("list-done", "Done")
    projects_list = _make_trello_list("list-proj", "Projects")
    project_card = _make_trello_card("project-card-1", "myapp", "list-proj")

    captured_json: list[str] = []

    original_compute_diff = None

    def mock_call_trello(tool_name: str, params: dict) -> object:
        if tool_name == "get_lists":
            return [tasks_list, done_list, projects_list]
        if tool_name == "get_cards_by_list_id":
            list_id = params.get("list_id", "")
            if list_id == "list-tasks":
                return [tasks_card]
            return []
        if tool_name == "get_card":
            return project_card
        return {}

    import server.tools.trello_sync as trello_sync_mod

    original_compute_diff = trello_sync_mod.compute_diff

    def patched_compute_diff(trello_cards_json: str, *args, **kwargs):
        captured_json.append(trello_cards_json)
        return original_compute_diff(trello_cards_json, *args, **kwargs)

    with (
        patch("server.tools.trello_full_sync._call_trello_tool", side_effect=mock_call_trello),
        patch("server.tools.trello_full_sync.compute_diff", side_effect=patched_compute_diff),
    ):
        _sync_single_project(cfg, name)

    assert captured_json, "compute_diff was not called"
    first_call_data = json.loads(captured_json[0])
    keys_found = list(first_call_data.keys())
    assert "cards" in first_call_data, (
        f"Expected 'cards' key in trello_data passed to compute_diff, got: {keys_found}"
    )
    assert "checklists" not in first_call_data, (
        "Should NOT pass 'checklists' key to compute_diff (old model)"
    )
    assert isinstance(first_call_data["cards"], list)


def test_sync_does_not_propose_recreating_existing_cards_on_second_run(
    cfg_with_trello_project: tuple[ProjConfig, str],
) -> None:
    """When Trello already has the card for a todo, second sync proposes no card creation."""
    cfg, name = cfg_with_trello_project

    from server.lib.ids import next_todo_id
    from server.lib.models import Todo, TrelloSyncState
    from server.tools.trello_sync import (
        build_card_description,
        compute_desc_hash,
        format_card_title,
    )

    meta = storage.load_meta(cfg, name)
    todo = Todo(
        id=next_todo_id(meta),
        title="Existing Task",
        trello_card_id="card-existing-1",
    )
    # Simulate a previous sync state
    expected_title = format_card_title(name, todo.id, todo.title)
    expected_desc = build_card_description(todo, name)
    todo.trello_sync_state = TrelloSyncState(
        last_sync="2026-01-01T00:00:00",
        synced_name=expected_title,
        card_id="card-existing-1",
        list_id="list-tasks",
        desc_hash=compute_desc_hash(expected_desc),
    )
    storage.save_todos(cfg, name, [todo])
    storage.save_meta(cfg, meta)

    # Trello has the card in tasks list — titles + hash match
    tasks_card = _make_trello_card("card-existing-1", expected_title, "list-tasks", expected_desc)
    tasks_list = _make_trello_list("list-tasks", "proj-tasks")
    done_list = _make_trello_list("list-done", "Done")
    projects_list = _make_trello_list("list-proj", "Projects")
    project_card = _make_trello_card("project-card-1", "myapp", "list-proj")

    def mock_call_trello(tool_name: str, params: dict) -> object:
        if tool_name == "get_lists":
            return [tasks_list, done_list, projects_list]
        if tool_name == "get_cards_by_list_id":
            list_id = params.get("list_id", "")
            if list_id == "list-tasks":
                return [tasks_card]
            return []
        if tool_name == "get_card":
            return project_card
        return {}

    from server.tools.trello_sync import TrelloSyncPlan

    captured_plans: list[TrelloSyncPlan] = []
    original_cd = None
    import server.tools.trello_sync as tsm

    original_cd = tsm.compute_diff

    def capture_plan(trello_cards_json: str, *args, **kwargs):
        plan = original_cd(trello_cards_json, *args, **kwargs)
        captured_plans.append(plan)
        return plan

    with (
        patch("server.tools.trello_full_sync._call_trello_tool", side_effect=mock_call_trello),
        patch("server.tools.trello_full_sync.compute_diff", side_effect=capture_plan),
    ):
        _sync_single_project(cfg, name)

    assert captured_plans, "compute_diff was not called"
    plan = captured_plans[0]
    assert plan.push_create_card == [], (
        f"Should not propose creating cards for existing todo: {plan.push_create_card}"
    )


def test_pull_updates_todo_title_from_trello_card_rename(
    cfg_with_trello_project: tuple[ProjConfig, str],
) -> None:
    """When Trello card title differs from local (Trello changed), pull_update is emitted."""
    cfg, name = cfg_with_trello_project

    from server.lib.ids import next_todo_id
    from server.lib.models import Todo, TrelloSyncState
    from server.tools.trello_sync import (
        build_card_description,
        compute_desc_hash,
        format_card_title,
    )

    meta = storage.load_meta(cfg, name)
    todo = Todo(
        id=next_todo_id(meta),
        title="Old Title",
        trello_card_id="card-rename-1",
    )
    # Record the original sync state
    old_title = format_card_title(name, todo.id, "Old Title")
    old_desc = build_card_description(todo, name)
    todo.trello_sync_state = TrelloSyncState(
        last_sync="2026-01-01T00:00:00",
        synced_name=old_title,
        card_id="card-rename-1",
        list_id="list-tasks",
        desc_hash=compute_desc_hash(old_desc),
    )
    storage.save_todos(cfg, name, [todo])
    storage.save_meta(cfg, meta)

    # Trello card was renamed
    new_trello_title = format_card_title(name, todo.id, "New Title From Trello")
    renamed_card = _make_trello_card("card-rename-1", new_trello_title, "list-tasks", old_desc)
    tasks_list = _make_trello_list("list-tasks", "proj-tasks")
    done_list = _make_trello_list("list-done", "Done")
    projects_list = _make_trello_list("list-proj", "Projects")
    project_card = _make_trello_card("project-card-1", "myapp", "list-proj")

    def mock_call_trello(tool_name: str, params: dict) -> object:
        if tool_name == "get_lists":
            return [tasks_list, done_list, projects_list]
        if tool_name == "get_cards_by_list_id":
            list_id = params.get("list_id", "")
            if list_id == "list-tasks":
                return [renamed_card]
            return []
        if tool_name == "get_card":
            return project_card
        return {}

    from server.tools.trello_sync import TrelloSyncPlan

    captured_plans: list[TrelloSyncPlan] = []
    import server.tools.trello_sync as tsm

    orig = tsm.compute_diff

    def capture_plan(trello_cards_json: str, *args, **kwargs):
        plan = orig(trello_cards_json, *args, **kwargs)
        captured_plans.append(plan)
        return plan

    with (
        patch("server.tools.trello_full_sync._call_trello_tool", side_effect=mock_call_trello),
        patch("server.tools.trello_full_sync.compute_diff", side_effect=capture_plan),
    ):
        _sync_single_project(cfg, name)

    assert captured_plans, "compute_diff was not called"
    plan = captured_plans[0]
    # Trello changed the title → pull_update should contain the todo id
    pulled_ids = [str(p.get("todo_id", "")) for p in plan.pull_update]
    assert todo.id in pulled_ids, (
        f"Expected pull_update for todo {todo.id!r}, got pull_update={plan.pull_update}"
    )
