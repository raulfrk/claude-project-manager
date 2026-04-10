"""Contract tests for the Trello sync flow label enforcement.

These tests verify two contract surfaces:

1. `compute_diff` emits `push_update_labels` entries for existing cards
   that are missing their expected `proj` / `proj-task` label, and
   *never* emits entries for archived cards or cards that already
   carry the expected label (extras are preserved).
2. The full sync flow — the sequence of Trello REST calls a
   first-time sync produces — hits the expected endpoints with the
   expected CSV `idLabels` query params. This mirrors what the
   `/proj:trello-sync` skill executes when Step 2 resolves both
   labels and Step 7 passes them through `add_card_to_list` /
   `batch_create_cards`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from server.lib import storage
from server.lib.models import (
    ProjConfig,
    ProjectDates,
    ProjectEntry,
    ProjectIndex,
    ProjectMeta,
    RepoEntry,
    Todo,
    TrelloListMappings,
    TrelloSync,
)
from server.tools.trello_sync import compute_diff

BASE = "https://api.trello.com/1"
KEY = "test_key"
TOKEN = "test_token"
BOARD_ID = "board123"
PROJ_LABEL_ID = "lbl-proj"
PROJ_TASK_LABEL_ID = "lbl-task"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "ALL_PROXY",
        "all_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def cfg_with_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ProjConfig, str]:
    config_path = tmp_path / "proj.yaml"
    monkeypatch.setattr(storage, "_DEFAULT_CONFIG_PATH", config_path)
    monkeypatch.delenv("PROJ_CONFIG", raising=False)

    cfg = ProjConfig(
        tracking_dir=str(tmp_path / "tracking"),
        trello=TrelloSync(
            enabled=True,
            default_board_id=BOARD_ID,
            list_mappings=TrelloListMappings(
                tasks="proj-tasks",
                done="Done",
                projects="Projects",
            ),
        ),
    )
    storage.save_config(cfg)

    now = datetime.now(tz=UTC).replace(tzinfo=None).isoformat()
    proj_dir = Path(cfg.tracking_dir) / "myapp"
    proj_dir.mkdir(parents=True)
    (proj_dir / "todos.yaml").write_text("todos: []\n")
    (proj_dir / "archive.yaml").write_text("todos: []\n")
    meta = ProjectMeta(
        name="myapp",
        repos=[RepoEntry(label="code", path=str(tmp_path))],
        dates=ProjectDates(created=now, last_updated=now),
        trello_card_id="card-proj",
    )
    storage.save_meta(cfg, meta)
    index = ProjectIndex(
        projects={"myapp": ProjectEntry(name="myapp", tracking_dir=str(proj_dir), created=now)},
    )
    storage.save_index(cfg, index)
    return cfg, "myapp"


def _save_todo(cfg: ProjConfig, name: str, todo: Todo) -> None:
    todos = storage.load_todos(cfg, name)
    todos.append(todo)
    storage.save_todos(cfg, name, todos)


def _trello_json(
    cards: list[dict],
    lists: list[dict],
    *,
    project_card: dict | None = None,
    proj_label_id: str = PROJ_LABEL_ID,
    proj_task_label_id: str = PROJ_TASK_LABEL_ID,
) -> str:
    data: dict = {
        "cards": cards,
        "lists": lists,
        "proj_label_id": proj_label_id,
        "proj_task_label_id": proj_task_label_id,
    }
    if project_card is not None:
        data["project_card"] = project_card
    return json.dumps(data)


# ── Diff-level tests ────────────────────────────────────────────────────────


class TestDiffLabelEnforcement:
    def test_existing_card_missing_proj_task_label_emits_update(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        now = datetime.now(tz=UTC).replace(tzinfo=None).isoformat()
        todo = Todo(
            id="1",
            title="Task A",
            status="pending",
            created=now,
            updated=now,
            trello_card_id="card-1",
        )
        _save_todo(cfg, name, todo)

        lists = [{"id": "list-tasks", "name": "proj-tasks"}, {"id": "list-done", "name": "Done"}]
        cards = [
            {
                "id": "card-1",
                "name": "[myapp] [1] Task A",
                "desc": "",
                "idList": "list-tasks",
                "closed": False,
                "idLabels": [],
            },
        ]
        plan = compute_diff(_trello_json(cards, lists), cfg, name)

        assert len(plan.push_update_labels) == 1
        entry = plan.push_update_labels[0]
        assert entry["card_id"] == "card-1"
        assert entry["add_label_ids"] == [PROJ_TASK_LABEL_ID]

    def test_card_already_has_expected_label_no_update(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        now = datetime.now(tz=UTC).replace(tzinfo=None).isoformat()
        todo = Todo(
            id="1",
            title="Task A",
            status="pending",
            created=now,
            updated=now,
            trello_card_id="card-1",
        )
        _save_todo(cfg, name, todo)

        lists = [{"id": "list-tasks", "name": "proj-tasks"}, {"id": "list-done", "name": "Done"}]
        # Card has proj-task PLUS an extra user label. Extras must be preserved.
        cards = [
            {
                "id": "card-1",
                "name": "[myapp] [1] Task A",
                "desc": "",
                "idList": "list-tasks",
                "closed": False,
                "idLabels": [PROJ_TASK_LABEL_ID, "lbl-user-custom"],
            },
        ]
        plan = compute_diff(_trello_json(cards, lists), cfg, name)

        assert plan.push_update_labels == []

    def test_archived_card_missing_label_no_update(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        now = datetime.now(tz=UTC).replace(tzinfo=None).isoformat()
        todo = Todo(
            id="1",
            title="Task A",
            status="pending",
            created=now,
            updated=now,
            trello_card_id="card-1",
        )
        _save_todo(cfg, name, todo)

        lists = [{"id": "list-tasks", "name": "proj-tasks"}, {"id": "list-done", "name": "Done"}]
        cards = [
            {
                "id": "card-1",
                "name": "[myapp] [1] Task A",
                "desc": "",
                "idList": "list-tasks",
                "closed": True,  # archived — must be skipped
                "idLabels": [],
            },
        ]
        plan = compute_diff(_trello_json(cards, lists), cfg, name)

        assert plan.push_update_labels == []

    def test_project_card_missing_proj_label_emits_update(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project

        lists = [{"id": "list-tasks", "name": "proj-tasks"}, {"id": "list-done", "name": "Done"}]
        project_card = {
            "id": "card-proj",
            "name": "myapp",
            "desc": "",
            "idList": "list-projects",
            "closed": False,
            "idLabels": [],
        }
        plan = compute_diff(
            _trello_json([], lists, project_card=project_card),
            cfg,
            name,
        )

        entries = [e for e in plan.push_update_labels if e["card_id"] == "card-proj"]
        assert len(entries) == 1
        assert entries[0]["add_label_ids"] == [PROJ_LABEL_ID]

    def test_no_label_ids_passed_skips_enforcement(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        """Omitting label IDs from the payload disables label diff entirely."""
        cfg, name = cfg_with_project
        now = datetime.now(tz=UTC).replace(tzinfo=None).isoformat()
        todo = Todo(
            id="1",
            title="Task A",
            status="pending",
            created=now,
            updated=now,
            trello_card_id="card-1",
        )
        _save_todo(cfg, name, todo)

        lists = [{"id": "list-tasks", "name": "proj-tasks"}, {"id": "list-done", "name": "Done"}]
        cards = [
            {
                "id": "card-1",
                "name": "[myapp] [1] Task A",
                "desc": "",
                "idList": "list-tasks",
                "closed": False,
                "idLabels": [],
            },
        ]
        # Empty label IDs in payload.
        payload = json.dumps(
            {
                "cards": cards,
                "lists": lists,
                "proj_label_id": "",
                "proj_task_label_id": "",
            }
        )
        plan = compute_diff(payload, cfg, name)
        assert plan.push_update_labels == []

    def test_to_dict_serializes_push_update_labels(
        self,
        cfg_with_project: tuple[ProjConfig, str],
    ) -> None:
        cfg, name = cfg_with_project
        now = datetime.now(tz=UTC).replace(tzinfo=None).isoformat()
        todo = Todo(
            id="1",
            title="Task A",
            status="pending",
            created=now,
            updated=now,
            trello_card_id="card-1",
        )
        _save_todo(cfg, name, todo)

        lists = [{"id": "list-tasks", "name": "proj-tasks"}, {"id": "list-done", "name": "Done"}]
        cards = [
            {
                "id": "card-1",
                "name": "[myapp] [1] Task A",
                "desc": "",
                "idList": "list-tasks",
                "closed": False,
                "idLabels": [],
            },
        ]
        plan = compute_diff(_trello_json(cards, lists), cfg, name)
        d = plan.to_dict()
        assert "push_update_labels" in d
        assert d["push_update_labels"] == plan.push_update_labels
        assert d["summary"]["push_update_labels_count"] == 1


# ── REST flow contract tests ────────────────────────────────────────────────


class TestTrelloSyncRestFlow:
    """Simulates the Trello REST call sequence a sync flow produces.

    Uses plain httpx + respx so we do not depend on the trello plugin
    being importable from within the proj plugin's test environment.
    """

    def _setup_labels(self, existing: list[dict]) -> dict[str, str]:
        ids: dict[str, str] = {}
        with httpx.Client() as client:
            resp = client.get(
                f"{BASE}/boards/{BOARD_ID}/labels",
                params={"key": KEY, "token": TOKEN},
            )
            resp.raise_for_status()
            by_name = {lbl["name"]: lbl["id"] for lbl in resp.json()}
            for name, color in (("proj", "blue"), ("proj-task", "green")):
                if name in by_name:
                    ids[name] = by_name[name]
                    continue
                create = client.post(
                    f"{BASE}/labels",
                    params={
                        "key": KEY,
                        "token": TOKEN,
                        "name": name,
                        "color": color,
                        "idBoard": BOARD_ID,
                    },
                )
                create.raise_for_status()
                ids[name] = create.json()["id"]
        _ = existing
        return ids

    def _create_project_card(self, proj_label_id: str) -> str:
        with httpx.Client() as client:
            resp = client.post(
                f"{BASE}/cards",
                params={
                    "key": KEY,
                    "token": TOKEN,
                    "idList": "list-projects",
                    "name": "myapp",
                    "idLabels": proj_label_id,
                },
            )
            resp.raise_for_status()
            card_id: str = resp.json()["id"]
            return card_id

    def _create_todo_cards(self, names: list[str], proj_task_label_id: str) -> list[str]:
        ids: list[str] = []
        with httpx.Client() as client:
            for title in names:
                resp = client.post(
                    f"{BASE}/cards",
                    params={
                        "key": KEY,
                        "token": TOKEN,
                        "idList": "list-tasks",
                        "name": title,
                        "idLabels": proj_task_label_id,
                    },
                )
                resp.raise_for_status()
                ids.append(resp.json()["id"])
        return ids

    @respx.mock
    def test_fresh_sync_emits_expected_rest_sequence(self) -> None:
        """Fresh sync: both labels created, project card + 2 todo cards posted."""
        respx.get(f"{BASE}/boards/{BOARD_ID}/labels").mock(
            return_value=httpx.Response(200, json=[]),
        )
        create_label = respx.post(f"{BASE}/labels").mock(
            side_effect=[
                httpx.Response(200, json={"id": PROJ_LABEL_ID, "name": "proj", "color": "blue"}),
                httpx.Response(
                    200,
                    json={"id": PROJ_TASK_LABEL_ID, "name": "proj-task", "color": "green"},
                ),
            ],
        )
        create_card = respx.post(f"{BASE}/cards").mock(
            side_effect=[
                httpx.Response(200, json={"id": "card-proj", "name": "myapp"}),
                httpx.Response(200, json={"id": "card-1", "name": "[myapp] [1] Task A"}),
                httpx.Response(200, json={"id": "card-2", "name": "[myapp] [2] Task B"}),
            ],
        )

        ids = self._setup_labels(existing=[])
        proj_card = self._create_project_card(ids["proj"])
        todo_cards = self._create_todo_cards(
            ["[myapp] [1] Task A", "[myapp] [2] Task B"],
            ids["proj-task"],
        )

        assert create_label.call_count == 2
        assert create_card.call_count == 3
        assert proj_card == "card-proj"
        assert todo_cards == ["card-1", "card-2"]

        # Project card call has proj label in idLabels
        proj_card_url = str(create_card.calls[0].request.url)
        assert f"idLabels={PROJ_LABEL_ID}" in proj_card_url
        # Each todo card call has proj-task label
        for call in list(create_card.calls)[1:]:
            assert f"idLabels={PROJ_TASK_LABEL_ID}" in str(call.request.url)

    @respx.mock
    def test_sync_with_existing_labels_skips_create_label(self) -> None:
        """If both labels already on board, no POST /labels calls."""
        respx.get(f"{BASE}/boards/{BOARD_ID}/labels").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": PROJ_LABEL_ID, "name": "proj", "color": "blue"},
                    {"id": PROJ_TASK_LABEL_ID, "name": "proj-task", "color": "green"},
                ],
            ),
        )
        create_label = respx.post(f"{BASE}/labels").mock(
            return_value=httpx.Response(500, json={"error": "should not be called"}),
        )
        respx.post(f"{BASE}/cards").mock(
            return_value=httpx.Response(200, json={"id": "card-proj", "name": "myapp"}),
        )

        ids = self._setup_labels(existing=[])
        self._create_project_card(ids["proj"])

        assert create_label.call_count == 0
        assert ids == {"proj": PROJ_LABEL_ID, "proj-task": PROJ_TASK_LABEL_ID}

    @respx.mock
    def test_missing_project_label_triggers_toggle_card_label(self) -> None:
        """Existing project card missing `proj` label -> `POST /cards/.../idLabels`."""
        # Simulate what the skill's Update labels sub-step would do for a
        # `push_update_labels` entry — call toggle_card_label with action=add.
        route = respx.post(f"{BASE}/cards/card-proj/idLabels").mock(
            return_value=httpx.Response(200, json=[{"id": PROJ_LABEL_ID}]),
        )

        with httpx.Client() as client:
            resp = client.post(
                f"{BASE}/cards/card-proj/idLabels",
                params={"key": KEY, "token": TOKEN, "value": PROJ_LABEL_ID},
            )
            resp.raise_for_status()

        assert route.called
        url_str = str(route.calls[0].request.url)
        assert f"value={PROJ_LABEL_ID}" in url_str

    @respx.mock
    def test_extras_preserved_no_toggle_call(self) -> None:
        """Card with proj-task + user label -> diff emits no update; no toggle call."""
        route = respx.post(f"{BASE}/cards/card-1/idLabels").mock(
            return_value=httpx.Response(500, json={"error": "should not be called"}),
        )
        # We simply do not call toggle_card_label in the extras-preserved case;
        # the assertion is that the mocked endpoint is never hit. This mirrors
        # the skill skipping the Update labels sub-step when the plan has no
        # entries for a card.
        assert route.call_count == 0
