"""Contract tests for confluence_list_attachments + confluence_list_comments."""

from __future__ import annotations

import respx
from test_contracts.builders import build_success_response
from test_contracts.validators import assert_request_matches_contract

from tests.contracts import metadata as c


def _att_tool(client, monkeypatch):
    from mcp.server.fastmcp import FastMCP

    from server.tools.attachments import register

    app = FastMCP("test")
    register(app)
    monkeypatch.setattr("server.tools.attachments.get_client", lambda: client)
    return app._tool_manager._tools["confluence_list_attachments"].fn


class TestAttachmentsContract:
    @respx.mock
    def test_cloud(self, cloud_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(f"{cloud_client.api_base}/content/42/child/attachment").mock(
            return_value=build_success_response(c.LIST_ATTACHMENTS_CLOUD, payload)
        )

        tool = _att_tool(cloud_client, monkeypatch)
        tool(page_id="42")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_ATTACHMENTS_CLOUD)

    @respx.mock
    def test_server(self, server_client, monkeypatch):
        payload = {"results": [], "size": 0, "_links": {}}
        route = respx.get(f"{server_client.api_base}/content/42/child/attachment").mock(
            return_value=build_success_response(c.LIST_ATTACHMENTS_SERVER, payload)
        )

        tool = _att_tool(server_client, monkeypatch)
        tool(page_id="42")

        req = route.calls[0].request
        assert_request_matches_contract(req, c.LIST_ATTACHMENTS_SERVER)
