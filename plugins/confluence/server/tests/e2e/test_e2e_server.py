"""Live Server E2E tests. Gated by CONFLUENCE_E2E_SERVER=1 + creds."""

from __future__ import annotations

import os

import pytest

from server.lib.client import ConfluenceClient
from server.lib.config import ConfluenceConfig

pytestmark = [
    pytest.mark.e2e_server,
    pytest.mark.skipif(
        os.environ.get("CONFLUENCE_E2E_SERVER") != "1",
        reason="set CONFLUENCE_E2E_SERVER=1 to run",
    ),
]


@pytest.fixture(scope="module")
def server_client() -> ConfluenceClient:
    cfg = ConfluenceConfig(
        deployment="server",
        base_url=os.environ["CONFLUENCE_E2E_SERVER_BASE_URL"],
        personal_access_token=os.environ["CONFLUENCE_E2E_SERVER_PAT"],
    )
    return ConfluenceClient(cfg)


@pytest.fixture(scope="module")
def test_space_key() -> str:
    return os.environ["CONFLUENCE_E2E_SERVER_TEST_SPACE_KEY"]


@pytest.fixture(scope="module")
def test_page_id() -> str:
    return os.environ["CONFLUENCE_E2E_SERVER_TEST_PAGE_ID"]


def test_list_spaces(server_client, test_space_key):
    data = server_client.get("/space", params={"limit": 50})
    assert "results" in data
    keys = [s.get("key") for s in data["results"]]
    assert test_space_key in keys


def test_search(server_client, test_space_key):
    data = server_client.get(
        "/search",
        params={"cql": f"space = {test_space_key} AND type = page", "limit": 1},
    )
    assert "results" in data


def test_get_page(server_client, test_page_id):
    data = server_client.get(
        f"/content/{test_page_id}",
        params={"expand": "body.view,version,space"},
    )
    assert data.get("id") == test_page_id


def test_list_pages_in_space(server_client, test_space_key):
    data = server_client.get(
        "/content",
        params={"type": "page", "spaceKey": test_space_key, "limit": 1},
    )
    assert "results" in data


def test_list_attachments(server_client, test_page_id):
    data = server_client.get(
        f"/content/{test_page_id}/child/attachment",
        params={"limit": 5},
    )
    assert "results" in data


def test_list_comments(server_client, test_page_id):
    data = server_client.get(
        f"/content/{test_page_id}/child/comment",
        params={"limit": 5, "expand": "body.view,version"},
    )
    assert "results" in data
