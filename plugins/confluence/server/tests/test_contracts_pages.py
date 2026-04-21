"""Contract tests for confluence page tools — Cloud + Server."""

from __future__ import annotations

import respx
from test_contracts.builders import build_success_response
from test_contracts.validators import assert_request_matches_contract

from tests.contracts import pages as c


def _get_page_tool(client, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from server.tools.pages import register

    app = FastMCP("test")
    register(app)
    monkeypatch.setattr("server.tools.pages.get_client", lambda: client)
    return app._tool_manager._tools["confluence_get_page"].fn


class TestGetPageContract:
    @respx.mock
    def test_cloud_by_id(self, cloud_client, monkeypatch):
        payload = {
            "id": "42",
            "title": "T",
            "version": {"number": 1},
            "space": {"key": "DOCS"},
            "body": {"view": {"value": "<p>x</p>"}},
            "_links": {"webui": "/"},
        }
        route = respx.get(f"{cloud_client.api_base}/content/42").mock(
            return_value=build_success_response(c.GET_PAGE_CLOUD, payload)
        )

        tool = _get_page_tool(cloud_client, monkeypatch)
        tool(page_id="42")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_PAGE_CLOUD)

    @respx.mock
    def test_server_by_id(self, server_client, monkeypatch):
        payload = {
            "id": "42",
            "title": "T",
            "version": {"number": 1},
            "space": {"key": "DOCS"},
            "body": {"view": {"value": "<p>x</p>"}},
            "_links": {"webui": "/"},
        }
        route = respx.get(f"{server_client.api_base}/content/42").mock(
            return_value=build_success_response(c.GET_PAGE_SERVER, payload)
        )

        tool = _get_page_tool(server_client, monkeypatch)
        tool(page_id="42")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_PAGE_SERVER)

    @respx.mock
    def test_cloud_by_title(self, cloud_client, monkeypatch):
        payload = {
            "results": [
                {
                    "id": "42",
                    "title": "T",
                    "version": {"number": 1},
                    "space": {"key": "DOCS"},
                    "body": {"view": {"value": "<p>x</p>"}},
                    "_links": {"webui": "/"},
                }
            ],
            "size": 1,
        }
        route = respx.get(f"{cloud_client.api_base}/content").mock(
            return_value=build_success_response(c.GET_PAGE_BY_TITLE_CLOUD, payload)
        )

        tool = _get_page_tool(cloud_client, monkeypatch)
        tool(title="T", space_key="DOCS")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.GET_PAGE_BY_TITLE_CLOUD)
        assert "spaceKey=DOCS" in str(req.url)
        assert "title=T" in str(req.url)


def _list_pages_tool(client, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from server.tools.pages import register

    app = FastMCP("test")
    register(app)
    monkeypatch.setattr("server.tools.pages.get_client", lambda: client)
    return app._tool_manager._tools["confluence_list_pages"].fn


class TestListPagesContract:
    @respx.mock
    def test_cloud(self, cloud_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(f"{cloud_client.api_base}/content").mock(
            return_value=build_success_response(c.LIST_PAGES_CLOUD, payload)
        )

        tool = _list_pages_tool(cloud_client, monkeypatch)
        tool(space_key="DOCS")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_PAGES_CLOUD)
        assert "type=page" in str(req.url)
        assert "spaceKey=DOCS" in str(req.url)

    @respx.mock
    def test_server(self, server_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(f"{server_client.api_base}/content").mock(
            return_value=build_success_response(c.LIST_PAGES_SERVER, payload)
        )

        tool = _list_pages_tool(server_client, monkeypatch)
        tool(space_key="DOCS")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_PAGES_SERVER)
