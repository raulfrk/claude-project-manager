# installer/tests/migrations/test_trello_resync.py
from __future__ import annotations

from pathlib import Path

import pytest
import respx
import yaml
from httpx import Response

from installer.migrations.integrations.trello import TrelloResync, _load_trello_cfg
from installer.migrations.integrations.base import Action
from installer.migrations.types import PendingProject, TodoRef


@pytest.fixture
def project_with_trello(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> PendingProject:
    # Global integration config lives in ~/.claude/proj.yaml — point HOME at tmp.
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "proj.yaml").write_text(
        yaml.safe_dump(
            {
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
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    root = tmp_path / "demo"
    root.mkdir()
    (root / "todos.yaml").write_text("[]\n")
    return PendingProject(
        name="demo",
        path=root,
        schema_version_path=root / ".schema-version",
        current_version=1,
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


# ── 663: trello.yaml priority + proj.yaml fallback ────────────────────────────


def _actions_stub() -> list[Action]:
    return [
        Action(
            kind="promote_checklist_item",
            target_id="item-1",
            payload={
                "parent_card_id": "pc",
                "checklist_id": "cl",
                "child_todo_id": "1.1",
                "title": "x",
                "board_id": "b",
                "tasks_list_id": "t",
            },
        ),
        Action(
            kind="promote_checklist_item",
            target_id="item-2",
            payload={
                "parent_card_id": "pc",
                "checklist_id": "cl",
                "child_todo_id": "1.2",
                "title": "y",
                "board_id": "b",
                "tasks_list_id": "t",
            },
        ),
    ]


class TestLoadTrelloCfg:
    """Priority: ~/.claude/trello.yaml → proj.yaml sync.trello → {}."""

    def test_load_from_trello_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "trello.yaml").write_text(
            yaml.safe_dump({"api_key": "k-yaml", "token": "t-yaml"})
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        # proj.yaml values get overridden except plan fields (board_id, list_mappings).
        proj_cfg = {
            "sync": {
                "trello": {
                    "api_key": "k-ignored",
                    "api_token": "t-ignored",
                    "board_id": "board-from-proj",
                    "list_mappings": {"tasks": "list-from-proj"},
                }
            }
        }
        cfg = _load_trello_cfg(proj_cfg)
        assert cfg["api_key"] == "k-yaml"
        assert cfg["api_token"] == "t-yaml"
        # Plan fields still come from proj.yaml.
        assert cfg["board_id"] == "board-from-proj"
        assert cfg["list_mappings"] == {"tasks": "list-from-proj"}

    def test_trello_yaml_maps_token_to_api_token(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "trello.yaml").write_text(
            yaml.safe_dump({"api_key": "k", "token": "t-xyz"})
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        cfg = _load_trello_cfg({})
        assert cfg.get("api_token") == "t-xyz"

    def test_fallback_to_proj_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        proj_cfg = {
            "sync": {
                "trello": {
                    "api_key": "k-proj",
                    "api_token": "t-proj",
                    "board_id": "b",
                    "list_mappings": {"tasks": "l"},
                }
            }
        }
        cfg = _load_trello_cfg(proj_cfg)
        assert cfg["api_key"] == "k-proj"
        assert cfg["api_token"] == "t-proj"

    def test_returns_empty_when_both_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        assert _load_trello_cfg({}) == {}
        assert _load_trello_cfg(None) == {}

    def test_yaml_error_falls_back_to_proj_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "trello.yaml").write_text(":::broken\n")
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        proj_cfg = {
            "sync": {
                "trello": {"api_key": "k-proj", "api_token": "t-proj"},
            }
        }
        cfg = _load_trello_cfg(proj_cfg)
        assert cfg["api_key"] == "k-proj"


def test_execute_aborts_with_runbook_when_no_auth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing api_key/token → single synthetic FailedAction with runbook."""
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    (fake_home / ".claude" / "proj.yaml").write_text(
        yaml.safe_dump({"sync": {"trello": {"enabled": True}}})
    )
    monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
    project = PendingProject(
        name="demo",
        path=tmp_path / "demo",
        schema_version_path=tmp_path / "demo" / ".schema-version",
        current_version=1,
    )
    (tmp_path / "demo").mkdir()

    result = TrelloResync().execute(project, _actions_stub())

    assert result.aborted is True
    # Single synthetic failure — not one-per-action spam.
    assert len(result.failed) == 1
    fa = result.failed[0]
    assert fa.error_class == "ConfigError"
    assert "api_key/token" in fa.message
    assert "/proj:trello-sync" in fa.message
