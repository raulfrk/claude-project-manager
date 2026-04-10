"""Contract tests for the trello-sync skill's Step 2 label setup flow.

These tests exercise the expected REST call sequence the
`/proj:trello-sync` skill produces when resolving the `proj` and
`proj-task` labels on a board:

1. `GET /1/boards/{boardId}/labels` — list existing labels.
2. For each label name not already present, `POST /1/labels` with
   `name`, `color`, and `idBoard`.

The skill is the orchestrator, so these tests simulate the flow via
plain httpx calls intercepted by respx. That mirrors what the Trello
MCP server's `get_labels` and `create_label` tools actually emit.
"""

from __future__ import annotations

import httpx
import pytest
import respx

BASE = "https://api.trello.com/1"
BOARD_ID = "board-abc"
KEY = "test_key"
TOKEN = "test_token"


@pytest.fixture(autouse=True)
def _clear_proxy_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear proxy env vars so httpx.Client doesn't try to use SOCKS."""
    for var in (
        "ALL_PROXY",
        "all_proxy",
        "HTTPS_PROXY",
        "https_proxy",
        "HTTP_PROXY",
        "http_proxy",
    ):
        monkeypatch.delenv(var, raising=False)


def _run_label_setup(existing: list[dict]) -> dict[str, str]:
    """Simulate the skill's Step 2 label setup.

    Returns a mapping {label_name: label_id}. Uses httpx directly so
    the respx fixture can assert the REST call sequence.
    """
    ids: dict[str, str] = {}
    with httpx.Client() as client:
        # 1. get_labels
        resp = client.get(
            f"{BASE}/boards/{BOARD_ID}/labels",
            params={"key": KEY, "token": TOKEN},
        )
        resp.raise_for_status()
        labels = resp.json()
        by_name = {lbl["name"]: lbl["id"] for lbl in labels}

        for name, color in (("proj", "blue"), ("proj-task", "green")):
            if name in by_name:
                ids[name] = by_name[name]
                continue
            # 2. create_label
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
    _ = existing  # silence unused warning; fixture is inspected by respx
    return ids


class TestTrelloSetupContract:
    @respx.mock
    def test_first_time_creates_both_labels(self) -> None:
        """Empty board -> both `proj` (blue) and `proj-task` (green) POSTed."""
        respx.get(f"{BASE}/boards/{BOARD_ID}/labels").mock(
            return_value=httpx.Response(200, json=[]),
        )
        create_route = respx.post(f"{BASE}/labels").mock(
            side_effect=[
                httpx.Response(200, json={"id": "lbl-proj", "name": "proj", "color": "blue"}),
                httpx.Response(
                    200,
                    json={"id": "lbl-task", "name": "proj-task", "color": "green"},
                ),
            ],
        )

        ids = _run_label_setup(existing=[])

        assert create_route.call_count == 2
        # First POST is proj (blue).
        first_url = str(create_route.calls[0].request.url)
        assert "name=proj" in first_url
        assert "color=blue" in first_url
        assert f"idBoard={BOARD_ID}" in first_url
        # Second POST is proj-task (green).
        second_url = str(create_route.calls[1].request.url)
        assert "name=proj-task" in second_url
        assert "color=green" in second_url
        assert ids == {"proj": "lbl-proj", "proj-task": "lbl-task"}

    @respx.mock
    def test_existing_proj_only_creates_proj_task(self) -> None:
        """Board already has `proj` -> only `proj-task` POSTed."""
        respx.get(f"{BASE}/boards/{BOARD_ID}/labels").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": "lbl-proj", "name": "proj", "color": "blue"}],
            ),
        )
        create_route = respx.post(f"{BASE}/labels").mock(
            return_value=httpx.Response(
                200,
                json={"id": "lbl-task", "name": "proj-task", "color": "green"},
            ),
        )

        ids = _run_label_setup(existing=[])

        assert create_route.call_count == 1
        url = str(create_route.calls[0].request.url)
        assert "name=proj-task" in url
        assert "color=green" in url
        assert ids == {"proj": "lbl-proj", "proj-task": "lbl-task"}

    @respx.mock
    def test_both_existing_no_post(self) -> None:
        """Both labels already present -> zero POST /labels calls."""
        respx.get(f"{BASE}/boards/{BOARD_ID}/labels").mock(
            return_value=httpx.Response(
                200,
                json=[
                    {"id": "lbl-proj", "name": "proj", "color": "blue"},
                    {"id": "lbl-task", "name": "proj-task", "color": "green"},
                    {"id": "lbl-other", "name": "user-label", "color": "red"},
                ],
            ),
        )
        create_route = respx.post(f"{BASE}/labels").mock(
            return_value=httpx.Response(500, json={"error": "should not be called"}),
        )

        ids = _run_label_setup(existing=[])

        assert create_route.call_count == 0
        assert ids == {"proj": "lbl-proj", "proj-task": "lbl-task"}

    @respx.mock
    def test_existing_proj_task_only_creates_proj(self) -> None:
        """Only `proj-task` exists -> only `proj` POSTed."""
        respx.get(f"{BASE}/boards/{BOARD_ID}/labels").mock(
            return_value=httpx.Response(
                200,
                json=[{"id": "lbl-task", "name": "proj-task", "color": "green"}],
            ),
        )
        create_route = respx.post(f"{BASE}/labels").mock(
            return_value=httpx.Response(
                200,
                json={"id": "lbl-proj", "name": "proj", "color": "blue"},
            ),
        )

        ids = _run_label_setup(existing=[])

        assert create_route.call_count == 1
        url = str(create_route.calls[0].request.url)
        assert "name=proj" in url
        assert "color=blue" in url
        assert ids == {"proj": "lbl-proj", "proj-task": "lbl-task"}
