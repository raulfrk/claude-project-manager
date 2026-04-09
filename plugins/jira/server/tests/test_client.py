"""Tests for JiraClient: response handling, project access checks, and rate limiting."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from server.lib.client import JiraClient
from server.lib.config import JiraConfig


@pytest.fixture()
def config() -> JiraConfig:
    return JiraConfig(
        personal_access_token="test_pat",
        base_url="https://jira.example.com",
        allowed_project_keys=["PROJ", "DEV"],
        rate_limit_per_10s=3,
    )


@pytest.fixture()
def client(config: JiraConfig) -> JiraClient:
    with patch("server.lib.client.httpx.Client"):
        return JiraClient(config)


class TestHandleResponse:
    def test_success_returns_json(self, client: JiraClient) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.is_success = True
        resp.json.return_value = {"key": "PROJ-1"}

        result = client._handle_response(resp)

        assert result == {"key": "PROJ-1"}

    def test_error_raises_runtime_error(self, client: JiraClient) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.is_success = False
        resp.status_code = 404
        resp.text = "Not Found"

        with pytest.raises(RuntimeError, match="Jira API error 404: Not Found"):
            client._handle_response(resp)

    def test_server_error_includes_body(self, client: JiraClient) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.is_success = False
        resp.status_code = 500
        resp.text = '{"errorMessages":["Internal error"]}'

        with pytest.raises(RuntimeError, match="500"):
            client._handle_response(resp)


class TestCheckProjectAccess:
    def test_allowed_key_passes(self, client: JiraClient) -> None:
        # Should not raise
        client.check_project_access("PROJ")

    def test_disallowed_key_raises(self, client: JiraClient) -> None:
        with pytest.raises(RuntimeError, match="not in whitelist"):
            client.check_project_access("SECRET")

    def test_error_message_includes_allowed_keys(self, client: JiraClient) -> None:
        with pytest.raises(RuntimeError, match="Allowed: \\['PROJ', 'DEV'\\]"):
            client.check_project_access("SECRET")

    def test_empty_whitelist_raises(self) -> None:
        cfg = JiraConfig(
            personal_access_token="pat",
            base_url="https://jira.example.com",
            allowed_project_keys=[],
        )
        with patch("server.lib.client.httpx.Client"):
            c = JiraClient(cfg)

        with pytest.raises(RuntimeError, match="No projects in whitelist"):
            c.check_project_access("PROJ")


class TestRateLimit:
    def test_does_not_block_under_limit(self, client: JiraClient) -> None:
        """With limit=3, first 3 calls should not block."""
        start = time.monotonic()
        for _ in range(3):
            client._rate_limit()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0

    def test_blocks_when_at_limit(self, config: JiraConfig) -> None:
        """When rate limit is reached, _rate_limit should sleep."""
        with patch("server.lib.client.httpx.Client"):
            c = JiraClient(config)
        # Fill up the timestamps to the limit
        for _ in range(config.rate_limit_per_10s):
            c._rate_limit()

        with patch("server.lib.client.time.sleep") as mock_sleep:
            # Next call should trigger sleep
            c._rate_limit()
            mock_sleep.assert_called_once()
            # sleep_for should be positive (close to 10 seconds)
            sleep_duration = mock_sleep.call_args[0][0]
            assert sleep_duration > 0

    def test_evicts_old_timestamps(self, config: JiraConfig) -> None:
        """Timestamps older than 10s should be evicted."""
        with patch("server.lib.client.httpx.Client"):
            c = JiraClient(config)
        # Manually inject old timestamps
        old_time = time.monotonic() - 11
        for _ in range(config.rate_limit_per_10s):
            c._request_timestamps.append(old_time)

        # Should not block because all timestamps are older than 10s
        start = time.monotonic()
        c._rate_limit()
        elapsed = time.monotonic() - start
        assert elapsed < 1.0
        # Old timestamps should be evicted, only the new one remains
        assert len(c._request_timestamps) == 1
