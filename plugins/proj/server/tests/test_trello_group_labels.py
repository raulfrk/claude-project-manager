"""Tests for Trello group label feature.

Spec §6.1 — test_trello_group_labels.py (5 tests).

Tests focus on:
- _stable_color_for: deterministic color from tag name
- _ensure_group_label: lookup in existing labels list
- compute_diff: emits group_label_ensure + group_label_attach for group:* tags
- compute_diff pull path: emits pull_update_group_tags when Trello labels differ
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from server.lib import storage
from server.lib.ids import next_todo_id
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    ProjectTrelloConfig,
    RepoEntry,
    TrelloSync,
    TrelloSyncState,
)
from server.tools.trello_sync import (
    TRELLO_LABEL_COLORS,
    _ensure_group_label,
    _stable_color_for,
    build_card_description,
    compute_desc_hash,
    compute_diff,
    format_card_title,
)

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
        projects={"myapp": ProjectEntry(name="myapp", tracking_dir=str(proj_dir), created=today)}
    )
    storage.save_index(cfg, index)
    return cfg, "myapp"


def _make_trello_card(
    card_id: str,
    name: str,
    list_id: str,
    desc: str = "",
    label_ids: list[str] | None = None,
) -> dict:
    return {
        "id": card_id,
        "name": name,
        "desc": desc,
        "idList": list_id,
        "closed": False,
        "idLabels": label_ids or [],
    }


def _make_trello_list(list_id: str, name: str) -> dict:
    return {"id": list_id, "name": name}


def _make_board_label(label_id: str, name: str, color: str = "blue") -> dict:
    return {"id": label_id, "name": name, "color": color}


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_group_label_color_stable_across_runs() -> None:
    """Same tag always yields the same Trello color; result is always in palette."""
    color1 = _stable_color_for("group:475")
    color2 = _stable_color_for("group:475")
    assert color1 == color2, "Color must be stable (deterministic)"
    assert color1 in TRELLO_LABEL_COLORS, f"Color {color1!r} not in palette"

    # Different tags produce valid colors (may be same or different, both valid)
    color_other = _stable_color_for("group:999")
    assert color_other in TRELLO_LABEL_COLORS


def test_group_label_reused_on_second_sync() -> None:
    """_ensure_group_label finds existing label by name (avoids duplicate creation)."""
    existing = [
        _make_board_label("lbl-id-1", "group:475", "blue"),
        _make_board_label("lbl-id-2", "group:900", "red"),
    ]
    result = _ensure_group_label("board-1", "group:475", existing)
    assert result == "lbl-id-1", f"Expected existing label ID, got {result!r}"

    # Non-existent label returns None → caller should create it
    missing = _ensure_group_label("board-1", "group:999", existing)
    assert missing is None, f"Expected None for missing label, got {missing!r}"


def test_group_label_created_on_first_sync(
    cfg_with_trello_project: tuple[ProjConfig, str],
) -> None:
    """compute_diff emits group_label_ensure when group:* tag label is absent from board."""
    cfg, name = cfg_with_trello_project

    meta = storage.load_meta(cfg, name)
    from server.lib.models import Todo

    parent_todo = Todo(
        id=next_todo_id(meta),
        title="Parent task",
        tags=["group:101"],
        trello_card_id="card-grouped-1",
    )
    storage.save_todos(cfg, name, [parent_todo])
    storage.save_meta(cfg, meta)

    # No board labels — label does not exist yet
    tasks_list = _make_trello_list("list-tasks", "proj-tasks")
    done_list = _make_trello_list("list-done", "Done")
    card = _make_trello_card("card-grouped-1", "[myapp] [1] Parent task", "list-tasks")

    trello_data = json.dumps(
        {
            "cards": [card],
            "lists": [tasks_list, done_list],
            "project_card": {"id": "project-card-1", "desc": ""},
            "board_labels": [],  # empty — triggers ensure
        }
    )

    plan = compute_diff(trello_data, cfg, name)

    ensure_names = [str(e.get("name", "")) for e in plan.group_label_ensure]
    assert "group:101" in ensure_names, (
        f"Expected group:101 in group_label_ensure, got {ensure_names}"
    )


def test_card_gets_group_label_attached(
    cfg_with_trello_project: tuple[ProjConfig, str],
) -> None:
    """compute_diff emits group_label_attach for a card missing its group label."""
    cfg, name = cfg_with_trello_project

    meta = storage.load_meta(cfg, name)
    from server.lib.models import Todo

    todo = Todo(
        id=next_todo_id(meta),
        title="Grouped todo",
        tags=["group:200"],
        trello_card_id="card-attach-1",
    )
    storage.save_todos(cfg, name, [todo])
    storage.save_meta(cfg, meta)

    # Board has the label already (so ensure won't fire), but card doesn't have it
    board_label = _make_board_label("lbl-group-200", "group:200", "purple")
    tasks_list = _make_trello_list("list-tasks", "proj-tasks")
    done_list = _make_trello_list("list-done", "Done")
    # Card has empty idLabels → label not attached yet
    card = _make_trello_card(
        "card-attach-1", "[myapp] [1] Grouped todo", "list-tasks", label_ids=[]
    )

    trello_data = json.dumps(
        {
            "cards": [card],
            "lists": [tasks_list, done_list],
            "project_card": {"id": "project-card-1", "desc": ""},
            "board_labels": [board_label],
        }
    )

    plan = compute_diff(trello_data, cfg, name)

    attach_card_ids = [str(a.get("card_id", "")) for a in plan.group_label_attach]
    assert "card-attach-1" in attach_card_ids, (
        f"Expected card-attach-1 in group_label_attach, got {attach_card_ids}"
    )
    attach_names = [str(a.get("label_name", "")) for a in plan.group_label_attach]
    assert "group:200" in attach_names


def test_removing_group_label_in_trello_strips_local_group_tag_on_pull(
    cfg_with_trello_project: tuple[ProjConfig, str],
) -> None:
    """When Trello card no longer has group:* label, pull path removes local group tag."""
    cfg, name = cfg_with_trello_project

    meta = storage.load_meta(cfg, name)
    from server.lib.models import Todo

    # Todo has group:300 locally, but Trello card has no group labels
    todo = Todo(
        id=next_todo_id(meta),
        title="Was grouped",
        tags=["group:300"],
        trello_card_id="card-degroup-1",
    )
    expected_title = format_card_title(name, todo.id, todo.title)
    expected_desc = build_card_description(todo, name)
    todo.trello_sync_state = TrelloSyncState(
        last_sync="2026-01-01T00:00:00",
        synced_name=expected_title,
        card_id="card-degroup-1",
        list_id="list-tasks",
        desc_hash=compute_desc_hash(expected_desc),
    )
    storage.save_todos(cfg, name, [todo])
    storage.save_meta(cfg, meta)

    # Board has the group:300 label but card doesn't have it (user removed it)
    board_label = _make_board_label("lbl-group-300", "group:300", "green")
    tasks_list = _make_trello_list("list-tasks", "proj-tasks")
    done_list = _make_trello_list("list-done", "Done")
    card = _make_trello_card(
        "card-degroup-1",
        expected_title,
        "list-tasks",
        expected_desc,
        label_ids=[],  # label was removed in Trello
    )

    trello_data = json.dumps(
        {
            "cards": [card],
            "lists": [tasks_list, done_list],
            "project_card": {"id": "project-card-1", "desc": ""},
            "board_labels": [board_label],
        }
    )

    plan = compute_diff(trello_data, cfg, name)

    # Should have a pull_update_group_tags entry for this todo
    tag_updates = {str(u.get("todo_id", "")): u for u in plan.pull_update_group_tags}
    assert todo.id in tag_updates, (
        f"Expected pull_update_group_tags for todo {todo.id!r}, got {list(tag_updates.keys())}"
    )
    update = tag_updates[todo.id]
    remove_tags = list(update.get("remove_tags", []))
    assert "group:300" in remove_tags, f"Expected group:300 in remove_tags, got {remove_tags}"
