"""Tests for trello_full_sync helpers."""

from __future__ import annotations

import json
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.tools.trello_full_sync import _build_push_ops, _call_trello_tool


# ── _call_trello_tool envelope unwrapping ────────────────────────────────────


class _FakeResponse:
    """Minimal stand-in for httpx.Response."""

    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


def _patch_trello_call(payload: dict):
    """Return a context manager that patches _call_trello_tool's HTTP layer."""
    fake_resp = _FakeResponse(payload)
    fake_client = MagicMock()
    fake_client.post.return_value = fake_resp
    fake_client.__enter__ = MagicMock(return_value=fake_client)
    fake_client.__exit__ = MagicMock(return_value=False)

    return patch(
        "server.tools.trello_full_sync.httpx.Client",
        return_value=fake_client,
    )


def test_envelope_unwrap_json_list() -> None:
    """Envelope with JSON-encoded list string is parsed into a list."""
    inner = [{"id": "cl1", "name": "Tasks"}]
    payload = {"ok": True, "result": json.dumps(inner)}

    with _patch_trello_call(payload), patch(
        "server.tools.trello_full_sync._resolve_trello_socket",
        return_value="/tmp/fake.sock",
    ):
        result = _call_trello_tool("get_card_checklists", {"card_id": "abc"})

    assert result == inner


def test_envelope_unwrap_json_dict() -> None:
    """Envelope with JSON-encoded dict string is parsed into a dict."""
    inner = {"id": "123", "name": "My Card"}
    payload = {"ok": True, "result": json.dumps(inner)}

    with _patch_trello_call(payload), patch(
        "server.tools.trello_full_sync._resolve_trello_socket",
        return_value="/tmp/fake.sock",
    ):
        result = _call_trello_tool("get_card", {"card_id": "123"})

    assert result == inner


def test_envelope_error_raises() -> None:
    """Error envelope raises RuntimeError."""
    payload = {"ok": False, "error": "not found"}

    with _patch_trello_call(payload), patch(
        "server.tools.trello_full_sync._resolve_trello_socket",
        return_value="/tmp/fake.sock",
    ):
        with pytest.raises(RuntimeError, match="not found"):
            _call_trello_tool("get_card", {"card_id": "bad"})


def test_envelope_plain_string_result() -> None:
    """Non-JSON string result is returned as-is."""
    payload = {"ok": True, "result": "some-plain-text"}

    with _patch_trello_call(payload), patch(
        "server.tools.trello_full_sync._resolve_trello_socket",
        return_value="/tmp/fake.sock",
    ):
        result = _call_trello_tool("some_tool", {})

    assert result == "some-plain-text"


# ── snake_case parameter names ───────────────────────────────────────────────


def test_no_camel_case_params_in_source() -> None:
    """All _call_trello_tool call sites use snake_case parameter names."""
    src = Path(__file__).resolve().parent.parent / "server" / "tools" / "trello_full_sync.py"
    content = src.read_text()

    # These camelCase keys should never appear as dict keys in the source
    camel_keys = ["cardId", "boardId", "listId", "checklistId", "checkItemId"]
    for key in camel_keys:
        matches = re.findall(rf'"{key}"', content)
        assert not matches, f"Found camelCase key \"{key}\" in trello_full_sync.py"
