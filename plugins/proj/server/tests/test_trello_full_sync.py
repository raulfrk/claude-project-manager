"""Tests for trello_full_sync helpers."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from server.tools.trello_full_sync import _call_trello_tool, _execute_push_ops, _retry_failed_ops

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

    with (
        _patch_trello_call(payload),
        patch(
            "server.tools.trello_full_sync._resolve_trello_socket",
            return_value="/tmp/fake.sock",
        ),
    ):
        result = _call_trello_tool("get_card_checklists", {"card_id": "abc"})

    assert result == inner


def test_envelope_unwrap_json_dict() -> None:
    """Envelope with JSON-encoded dict string is parsed into a dict."""
    inner = {"id": "123", "name": "My Card"}
    payload = {"ok": True, "result": json.dumps(inner)}

    with (
        _patch_trello_call(payload),
        patch(
            "server.tools.trello_full_sync._resolve_trello_socket",
            return_value="/tmp/fake.sock",
        ),
    ):
        result = _call_trello_tool("get_card", {"card_id": "123"})

    assert result == inner


def test_envelope_error_raises() -> None:
    """Error envelope raises RuntimeError."""
    payload = {"ok": False, "error": "not found"}

    with (
        _patch_trello_call(payload),
        patch(
            "server.tools.trello_full_sync._resolve_trello_socket",
            return_value="/tmp/fake.sock",
        ),
        pytest.raises(RuntimeError, match="not found"),
    ):
        _call_trello_tool("get_card", {"card_id": "bad"})


def test_envelope_plain_string_result() -> None:
    """Non-JSON string result is returned as-is."""
    payload = {"ok": True, "result": "some-plain-text"}

    with (
        _patch_trello_call(payload),
        patch(
            "server.tools.trello_full_sync._resolve_trello_socket",
            return_value="/tmp/fake.sock",
        ),
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
        assert not matches, f'Found camelCase key "{key}" in trello_full_sync.py'


# ── Error visibility tests ────────────────────────────────────────────────────


def test_execute_push_ops_prefetch_failure_logs_error(caplog: pytest.LogCaptureFixture) -> None:
    """Transport error during checklist pre-fetch logs ERROR and falls back gracefully."""
    import httpx

    ops = [
        {
            "type": "push_create_checklist",
            "tool": "create_checklist",
            "params": {"card_id": "card1", "name": "Tasks"},
            "checklist_key": "t-1",
        }
    ]

    def _side_effect(tool_name: str, params: dict) -> object:
        if tool_name == "get_card_checklists":
            raise httpx.ConnectError("socket unreachable")
        # For the actual create_checklist call succeed
        return {"id": "new-cl", "name": "Tasks"}

    with (
        patch("server.tools.trello_full_sync._call_trello_tool", side_effect=_side_effect),
        caplog.at_level(logging.ERROR, logger="server.tools.trello_full_sync"),
    ):
        succeeded, errors = _execute_push_ops(ops, card_id="card1")

    # Pre-fetch failure should be logged at ERROR
    assert any(
        "pre-fetch" in r.message.lower()
        or "prefetch" in r.message.lower()
        or "fetch" in r.message.lower()
        for r in caplog.records
        if r.levelno == logging.ERROR
    )
    # The op itself should still proceed (succeeded or failed is ok, but not silently dropped)
    assert len(succeeded) + len(errors) == 1


def test_retry_failed_ops_checklist_fetch_failure_logs_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Transport error during retry dedup checklist fetch logs ERROR."""
    import httpx

    failed_ops = [
        {
            "operation_type": "push_create_checklist",
            "error": "timeout",
            "retryable": True,
            "retry_payload": {
                "type": "push_create_checklist",
                "tool": "create_checklist",
                "params": {"card_id": "card1", "name": "Tasks"},
            },
        }
    ]

    def _side_effect(tool_name: str, params: dict) -> object:
        if tool_name == "get_card_checklists":
            raise httpx.ConnectError("socket unreachable")
        # create_checklist succeeds
        return {"id": "new-cl", "name": "Tasks"}

    with (
        patch("server.tools.trello_full_sync._call_trello_tool", side_effect=_side_effect),
        caplog.at_level(logging.ERROR, logger="server.tools.trello_full_sync"),
    ):
        _succeeded, _still_failed = _retry_failed_ops(failed_ops)

    assert any(r.levelno == logging.ERROR for r in caplog.records)
