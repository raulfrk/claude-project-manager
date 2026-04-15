"""Tests for JiraClient: response handling, project access checks, and rate limiting."""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import httpx
import pytest

from server.lib.client import _MAX_RETRIES, JiraClient
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


class TestRetry:
    def _make_response(
        self,
        status_code: int,
        text: str = "",
        json_data: object = None,
    ) -> MagicMock:
        resp = MagicMock(spec=httpx.Response)
        resp.is_success = status_code < 400
        resp.status_code = status_code
        resp.text = text or str(status_code)
        if json_data is not None:
            resp.json.return_value = json_data
        return resp

    def test_retries_on_503(self, client: JiraClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Client retries on transient 503 errors."""
        fail_resp = self._make_response(503, "Service Unavailable")
        ok_resp = self._make_response(200, json_data={"key": "PROJ-1"})

        mock_get = MagicMock(side_effect=[fail_resp, fail_resp, ok_resp])
        monkeypatch.setattr(client._http, "get", mock_get)

        sleep_calls: list[float] = []
        monkeypatch.setattr("server.lib.client.time.sleep", lambda s: sleep_calls.append(s))

        result = client.get("/rest/api/2/issue/PROJ-1")

        assert result == {"key": "PROJ-1"}
        assert mock_get.call_count == 3
        assert len(sleep_calls) == 2

    def test_no_retry_on_400(self, client: JiraClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Client does not retry on 400 client errors."""
        fail_resp = self._make_response(400, "Bad Request")
        mock_get = MagicMock(return_value=fail_resp)
        monkeypatch.setattr(client._http, "get", mock_get)

        sleep_calls: list[float] = []
        monkeypatch.setattr("server.lib.client.time.sleep", lambda s: sleep_calls.append(s))

        with pytest.raises(RuntimeError, match="Jira API error 400"):
            client.get("/rest/api/2/issue/PROJ-1")

        assert mock_get.call_count == 1
        assert len(sleep_calls) == 0

    def test_exhausted_retries_raises(
        self,
        client: JiraClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """After max retries, last error is raised."""
        fail_resp = self._make_response(503, "Service Unavailable")
        mock_get = MagicMock(return_value=fail_resp)
        monkeypatch.setattr(client._http, "get", mock_get)

        monkeypatch.setattr("server.lib.client.time.sleep", lambda s: None)

        with pytest.raises(RuntimeError, match="Jira API error 503"):
            client.get("/rest/api/2/issue/PROJ-1")

        assert mock_get.call_count == _MAX_RETRIES

    def test_retries_on_429(self, client: JiraClient, monkeypatch: pytest.MonkeyPatch) -> None:
        """Client retries on 429 rate limit errors."""
        fail_resp = self._make_response(429, "Too Many Requests")
        ok_resp = self._make_response(200, json_data={"total": 0})

        mock_get = MagicMock(side_effect=[fail_resp, ok_resp])
        monkeypatch.setattr(client._http, "get", mock_get)

        monkeypatch.setattr("server.lib.client.time.sleep", lambda s: None)

        result = client.get("/rest/api/2/search")

        assert result == {"total": 0}
        assert mock_get.call_count == 2
