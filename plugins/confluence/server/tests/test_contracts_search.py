"""Contract tests for confluence_search — Cloud + Server."""

from __future__ import annotations

import pytest
import respx
from test_contracts.builders import build_success_response
from test_contracts.validators import assert_request_matches_contract

from tests.contracts import search as c


@pytest.fixture()
def search_tool(cloud_client, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from server.tools.search import register

    app = FastMCP("test")
    register(app)
    monkeypatch.setattr("server.tools.search.get_client", lambda: cloud_client)
    return app._tool_manager._tools["confluence_search"].fn


class TestSearchContractCloud:
    @respx.mock
    def test_request_shape(self, search_tool, cloud_client):
        payload = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
        route = respx.get(f"{cloud_client.api_base}/search").mock(
            return_value=build_success_response(c.SEARCH_CLOUD, payload)
        )

        search_tool(text="foo", limit=10)

        req = route.calls[0].request
        assert_request_matches_contract(req, c.SEARCH_CLOUD)
        assert req.headers["authorization"].startswith("Basic ")

    @respx.mock
    def test_response_parses(self, search_tool, cloud_client):
        payload = {
            "results": [
                {
                    "content": {"id": "1", "type": "page", "title": "T", "space": {"key": "DOCS"}},
                    "excerpt": "x",
                    "url": "/x",
                    "lastModified": "2026-04-20",
                }
            ],
            "size": 1,
            "totalSize": 1,
            "_links": {},
        }
        respx.get(f"{cloud_client.api_base}/search").mock(
            return_value=build_success_response(c.SEARCH_CLOUD, payload)
        )

        result = search_tool(text="foo")
        assert result["count"] == 1
        assert result["results"][0]["page_id"] == "1"


class TestSearchContractServer:
    @pytest.fixture()
    def search_tool_server(self, server_client, monkeypatch):
        from mcp.server.fastmcp import FastMCP

        from server.tools.search import register

        app = FastMCP("test")
        register(app)
        monkeypatch.setattr("server.tools.search.get_client", lambda: server_client)
        return app._tool_manager._tools["confluence_search"].fn

    @respx.mock
    def test_server_request_shape(self, search_tool_server, server_client):
        payload = {"results": [], "size": 0, "totalSize": 0, "_links": {}}
        route = respx.get(f"{server_client.api_base}/search").mock(
            return_value=build_success_response(c.SEARCH_SERVER, payload)
        )

        search_tool_server(text="foo")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.SEARCH_SERVER)
        assert req.headers["authorization"].startswith("Bearer ")
