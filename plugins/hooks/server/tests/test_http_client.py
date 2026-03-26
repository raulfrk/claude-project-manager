"""Tests for server.lib.http_client — FireResult and post_hook."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from server.lib.http_client import FireResult, post_hook


# ── FireResult tests ────────────────────────────────────────────────────────


class TestFireResult:
    def test_fire_result_has_result_field(self):
        """The result field exists and defaults to None."""
        fr = FireResult(hook_id="h1")
        assert fr.result is None

    def test_fire_result_result_field_settable(self):
        fr = FireResult(hook_id="h1", result="some-value")
        assert fr.result == "some-value"


# ── post_hook tests ─────────────────────────────────────────────────────────


class TestPostHook:
    @pytest.mark.asyncio
    async def test_post_hook_parses_success_json(self):
        """Response with {"ok": true, "result": ...} populates FireResult.result."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"ok": true, "result": "success"}'
        mock_resp.json.return_value = {"ok": True, "result": "success"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("server.lib.http_client.httpx.AsyncClient", return_value=mock_client):
            fr = await post_hook(
                hook_id="h1",
                url="http://localhost:9000/hook",
                target_tool="some_tool",
                params={"key": "val"},
            )

        assert fr.ok is True
        assert fr.result == "success"
        assert fr.error is None
        assert fr.status_code == 200

    @pytest.mark.asyncio
    async def test_post_hook_parses_error_json(self):
        """Response with {"ok": false, "error": ...} populates FireResult.error."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"ok": false, "error": "bad"}'
        mock_resp.json.return_value = {"ok": False, "error": "bad"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("server.lib.http_client.httpx.AsyncClient", return_value=mock_client):
            fr = await post_hook(
                hook_id="h1",
                url="http://localhost:9000/hook",
                target_tool="some_tool",
                params={},
            )

        assert fr.ok is False
        assert fr.error == "bad"
        assert fr.result is None

    @pytest.mark.asyncio
    async def test_post_hook_non_json_response(self):
        """Non-JSON response falls back to body-only FireResult, no crash."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "plain text response"
        mock_resp.json.side_effect = ValueError("No JSON")

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("server.lib.http_client.httpx.AsyncClient", return_value=mock_client):
            fr = await post_hook(
                hook_id="h1",
                url="http://localhost:9000/hook",
                target_tool="some_tool",
                params={},
            )

        assert fr.ok is False
        assert fr.body == "plain text response"
        assert fr.result is None
        assert "Non-JSON response" in fr.error

    @pytest.mark.asyncio
    async def test_post_hook_empty_response(self):
        """Empty response body sets error='Empty response'."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = ""

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("server.lib.http_client.httpx.AsyncClient", return_value=mock_client):
            fr = await post_hook(
                hook_id="h1",
                url="http://localhost:9000/hook",
                target_tool="some_tool",
                params={},
            )

        assert fr.ok is False
        assert fr.error == "Empty response"

    @pytest.mark.asyncio
    async def test_post_hook_null_result(self):
        """Response with null result returns None, not string 'None'."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"ok": true, "result": null}'
        mock_resp.json.return_value = {"ok": True, "result": None}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("server.lib.http_client.httpx.AsyncClient", return_value=mock_client):
            fr = await post_hook(
                hook_id="h1",
                url="http://localhost:9000/hook",
                target_tool="some_tool",
                params={},
            )

        assert fr.ok is True
        assert fr.result is None

    @pytest.mark.asyncio
    async def test_post_hook_4xx_with_json_error(self):
        """4xx response with JSON error body captures error message."""
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = '{"ok": false, "error": "Unknown tool: foo"}'
        mock_resp.json.return_value = {"ok": False, "error": "Unknown tool: foo"}

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("server.lib.http_client.httpx.AsyncClient", return_value=mock_client):
            fr = await post_hook(
                hook_id="h1",
                url="http://localhost:9000/hook",
                target_tool="nonexistent",
                params={},
            )

        assert fr.ok is False
        assert fr.error == "Unknown tool: foo"
        assert fr.status_code == 404
