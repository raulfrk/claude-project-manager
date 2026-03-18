"""Jira REST API client with rate limiting."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import httpx

from server.lib.config import JiraConfig, load_config


class JiraClient:
    """HTTP client for the Jira Server REST API."""

    def __init__(self, config: JiraConfig) -> None:
        self._config = config
        self._http = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            timeout=30,
            headers={"Authorization": f"Bearer {config.personal_access_token}"},
        )
        self._request_timestamps: deque[float] = deque()

    def check_project_access(self, project_key: str) -> None:
        """Raise if project_key is not in the configured whitelist."""
        if not self._config.allowed_project_keys:
            raise RuntimeError(
                "No projects in whitelist. Run jira_init to configure allowed project keys."
            )
        if project_key not in self._config.allowed_project_keys:
            raise RuntimeError(
                f"Project '{project_key}' not in whitelist. "
                f"Allowed: {self._config.allowed_project_keys}"
            )

    def _rate_limit(self) -> None:
        """Block if we've exceeded rate_limit_per_10s requests in the last 10 seconds."""
        now = time.monotonic()
        # Evict timestamps older than 10 seconds
        while self._request_timestamps and self._request_timestamps[0] < now - 10:
            self._request_timestamps.popleft()
        if len(self._request_timestamps) >= self._config.rate_limit_per_10s:
            sleep_for = 10 - (now - self._request_timestamps[0])
            if sleep_for > 0:
                time.sleep(sleep_for)
        self._request_timestamps.append(time.monotonic())

    def _handle_response(self, resp: httpx.Response) -> Any:  # noqa: ANN401
        if resp.is_success:
            return resp.json()
        msg = f"Jira API error {resp.status_code}: {resp.text}"
        raise RuntimeError(msg)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
        """Send a GET request to the Jira REST API."""
        self._rate_limit()
        return self._handle_response(self._http.get(path, params=params or {}))


_cached_client: JiraClient | None = None


def get_client() -> JiraClient:
    """Return a singleton JiraClient, creating it on first call."""
    global _cached_client  # noqa: PLW0603
    if _cached_client is None:
        _cached_client = JiraClient(load_config())
    return _cached_client
