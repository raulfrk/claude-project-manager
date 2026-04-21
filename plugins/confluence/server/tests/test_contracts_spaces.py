"""Contract tests for confluence_list_spaces."""

from __future__ import annotations

import respx
from test_contracts.builders import build_success_response
from test_contracts.validators import assert_request_matches_contract

from tests.contracts import spaces as c


def _tool(client, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from server.tools.spaces import register

    app = FastMCP("test")
    register(app)
    monkeypatch.setattr("server.tools.spaces.get_client", lambda: client)
    return app._tool_manager._tools["confluence_list_spaces"].fn


class TestListSpacesContract:
    @respx.mock
    def test_cloud(self, cloud_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(f"{cloud_client.api_base}/space").mock(
            return_value=build_success_response(c.LIST_SPACES_CLOUD, payload)
        )

        tool = _tool(cloud_client, monkeypatch)
        tool()

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_SPACES_CLOUD)

    @respx.mock
    def test_server(self, server_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(f"{server_client.api_base}/space").mock(
            return_value=build_success_response(c.LIST_SPACES_SERVER, payload)
        )

        tool = _tool(server_client, monkeypatch)
        tool()

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_SPACES_SERVER)
