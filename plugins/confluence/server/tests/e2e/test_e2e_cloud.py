"""Live Cloud E2E tests. Gated by CONFLUENCE_E2E_CLOUD=1 + creds."""

from __future__ import annotations

import os

import pytest

from server.lib.client import ConfluenceClient
from server.lib.config import ConfluenceConfig

pytestmark = [
    pytest.mark.e2e_cloud,
    pytest.mark.skipif(
        os.environ.get("CONFLUENCE_E2E_CLOUD") != "1",
        reason="set CONFLUENCE_E2E_CLOUD=1 to run",
    ),
]


@pytest.fixture(scope="module")
def cloud_client() -> ConfluenceClient:
    cfg = ConfluenceConfig(
        deployment="cloud",
        base_url=os.environ["CONFLUENCE_E2E_CLOUD_BASE_URL"],
        email=os.environ["CONFLUENCE_E2E_CLOUD_EMAIL"],
        api_token=os.environ["CONFLUENCE_E2E_CLOUD_API_TOKEN"],
    )
    return ConfluenceClient(cfg)


@pytest.fixture(scope="module")
def test_space_key() -> str:
    return os.environ["CONFLUENCE_E2E_CLOUD_TEST_SPACE_KEY"]


@pytest.fixture(scope="module")
def test_page_id() -> str:
    return os.environ["CONFLUENCE_E2E_CLOUD_TEST_PAGE_ID"]


def test_list_spaces(cloud_client, test_space_key):
    data = cloud_client.get("/space", params={"limit": 50})
    assert "results" in data
    keys = [s.get("key") for s in data["results"]]
    assert test_space_key in keys


def test_search(cloud_client, test_space_key):
    data = cloud_client.get(
        "/search",
        params={"cql": f"space = {test_space_key} AND type = page", "limit": 1},
    )
    assert "results" in data


def test_get_page(cloud_client, test_page_id):
    data = cloud_client.get(
        f"/content/{test_page_id}",
        params={"expand": "body.view,version,space"},
    )
    assert data.get("id") == test_page_id
    assert "body" in data


def test_list_pages_in_space(cloud_client, test_space_key):
    data = cloud_client.get(
        "/content",
        params={"type": "page", "spaceKey": test_space_key, "limit": 1},
    )
    assert "results" in data


def test_list_attachments(cloud_client, test_page_id):
    data = cloud_client.get(
        f"/content/{test_page_id}/child/attachment",
        params={"limit": 5},
    )
    assert "results" in data


def test_list_comments(cloud_client, test_page_id):
    data = cloud_client.get(
        f"/content/{test_page_id}/child/comment",
        params={"limit": 5, "expand": "body.view,version"},
    )
    assert "results" in data
