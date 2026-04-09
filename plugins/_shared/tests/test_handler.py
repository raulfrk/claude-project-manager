"""Tests for http_hook_handler — the /hook and /health endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from hook_transport.http_hook_handler import create_hook_app

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_tool():
    tool = MagicMock()
    tool.name = "test_tool"
    return tool


@pytest.fixture()
def mock_tool_manager(mock_tool):
    mgr = MagicMock()
    mgr.list_tools.return_value = [mock_tool]
    mgr.get_tool.return_value = mock_tool
    mgr.call_tool = AsyncMock(return_value="tool result")
    return mgr


@pytest.fixture()
def mock_mcp(mock_tool_manager):
    mcp = MagicMock()
    mcp._tool_manager = mock_tool_manager
    return mcp


@pytest.fixture()
def app(mock_mcp):
    return create_hook_app(mock_mcp)


@pytest.fixture()
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── /hook tests ───────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_hook_successful_dispatch(client, mock_tool_manager):
    resp = await client.post("/hook", json={"tool": "test_tool", "params": {"key": "val"}})
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert data["result"] == "tool result"
    mock_tool_manager.call_tool.assert_awaited_once_with(
        "test_tool", {"key": "val"}, context=None, convert_result=False
    )


@pytest.mark.anyio
async def test_hook_empty_params(client, mock_tool_manager):
    resp = await client.post("/hook", json={"tool": "test_tool"})
    assert resp.status_code == 200
    mock_tool_manager.call_tool.assert_awaited_once_with(
        "test_tool", {}, context=None, convert_result=False
    )


@pytest.mark.anyio
async def test_hook_missing_tool_field(client):
    resp = await client.post("/hook", json={"params": {}})
    assert resp.status_code == 400
    assert resp.json()["ok"] is False
    assert "tool" in resp.json()["error"].lower()


@pytest.mark.anyio
async def test_hook_malformed_json(client):
    resp = await client.post(
        "/hook", content=b"not json", headers={"content-type": "application/json"}
    )
    assert resp.status_code == 400
    assert resp.json()["ok"] is False


@pytest.mark.anyio
async def test_hook_unknown_tool(client, mock_tool_manager):
    mock_tool_manager.get_tool.return_value = None
    resp = await client.post("/hook", json={"tool": "nonexistent", "params": {}})
    assert resp.status_code == 404
    assert "Unknown tool" in resp.json()["error"]


@pytest.mark.anyio
async def test_hook_tool_exception(client, mock_tool_manager):
    mock_tool_manager.call_tool.side_effect = RuntimeError("boom")
    resp = await client.post("/hook", json={"tool": "test_tool", "params": {}})
    assert resp.status_code == 500
    assert "boom" in resp.json()["error"]


@pytest.mark.anyio
async def test_hook_tool_returns_dict(client, mock_tool_manager):
    mock_tool_manager.call_tool.return_value = {"key": "value"}
    resp = await client.post("/hook", json={"tool": "test_tool", "params": {}})
    assert resp.status_code == 200
    assert resp.json()["result"] == {"key": "value"}


@pytest.mark.anyio
async def test_hook_tool_returns_list(client, mock_tool_manager):
    mock_tool_manager.call_tool.return_value = ["a", "b"]
    resp = await client.post("/hook", json={"tool": "test_tool", "params": {}})
    assert resp.status_code == 200
    assert resp.json()["result"] == ["a", "b"]


@pytest.mark.anyio
async def test_hook_tool_returns_none(client, mock_tool_manager):
    mock_tool_manager.call_tool.return_value = None
    resp = await client.post("/hook", json={"tool": "test_tool", "params": {}})
    assert resp.status_code == 200
    assert resp.json()["result"] is None


@pytest.mark.anyio
async def test_hook_tool_returns_int(client, mock_tool_manager):
    mock_tool_manager.call_tool.return_value = 42
    resp = await client.post("/hook", json={"tool": "test_tool", "params": {}})
    assert resp.status_code == 200
    assert resp.json()["result"] == 42


@pytest.mark.anyio
async def test_hook_tool_returns_content_block_single(client, mock_tool_manager):
    """ContentBlock with .text attribute is serialized to string."""
    block = MagicMock()
    block.text = "hello from tool"
    mock_tool_manager.call_tool.return_value = [block]
    resp = await client.post("/hook", json={"tool": "test_tool", "params": {}})
    assert resp.status_code == 200
    assert resp.json()["result"] == "hello from tool"


@pytest.mark.anyio
async def test_hook_tool_returns_content_block_multiple(client, mock_tool_manager):
    """Multiple ContentBlocks are serialized to list of strings."""
    block1 = MagicMock()
    block1.text = "first"
    block2 = MagicMock()
    block2.text = "second"
    mock_tool_manager.call_tool.return_value = [block1, block2]
    resp = await client.post("/hook", json={"tool": "test_tool", "params": {}})
    assert resp.status_code == 200
    assert resp.json()["result"] == ["first", "second"]


@pytest.mark.anyio
async def test_hook_tool_returns_bool(client, mock_tool_manager):
    mock_tool_manager.call_tool.return_value = True
    resp = await client.post("/hook", json={"tool": "test_tool", "params": {}})
    assert resp.status_code == 200
    assert resp.json()["result"] is True


@pytest.mark.anyio
async def test_hook_invalid_params_type(client):
    resp = await client.post("/hook", json={"tool": "test_tool", "params": "not a dict"})
    assert resp.status_code == 400
    assert "params" in resp.json()["error"].lower()


@pytest.mark.anyio
async def test_hook_body_not_object(client):
    resp = await client.post("/hook", json=["not", "an", "object"])
    assert resp.status_code == 400
    assert "object" in resp.json()["error"].lower()


# ── /health tests ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_health_returns_tools(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "test_tool" in data["tools"]


@pytest.mark.anyio
async def test_health_empty_tools(client, mock_tool_manager):
    mock_tool_manager.list_tools.return_value = []
    resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["tools"] == []


@pytest.mark.anyio
async def test_health_multiple_tools(client, mock_tool_manager):
    tools = []
    for name in ["zebra", "alpha", "middle"]:
        t = MagicMock()
        t.name = name
        tools.append(t)
    mock_tool_manager.list_tools.return_value = tools
    resp = await client.get("/health")
    assert resp.json()["tools"] == ["alpha", "middle", "zebra"]
