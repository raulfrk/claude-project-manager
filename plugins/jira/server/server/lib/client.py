"""Jira REST API client with rate limiting."""

from __future__ import annotations

import time
from collections import deque
from pathlib import Path
from typing import TYPE_CHECKING

import httpx

from server.lib.config import JiraConfig, load_config

if TYPE_CHECKING:
    from collections.abc import Mapping

# Recursive JSON value type — no Any needed.
JsonValue = str | int | float | bool | None | dict[str, "JsonValue"] | list["JsonValue"]

# HTTP query-param values are always flat scalars.
ParamValue = str | int | float | bool


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

    def _handle_response(self, resp: httpx.Response) -> JsonValue:
        if resp.is_success:
            return resp.json()  # type: ignore[no-any-return]
        msg = f"Jira API error {resp.status_code}: {resp.text}"
        raise RuntimeError(msg)

    def get(
        self,
        path: str,
        params: Mapping[str, ParamValue] | None = None,
    ) -> JsonValue:
        """Send a GET request to the Jira REST API."""
        self._rate_limit()
        return self._handle_response(self._http.get(path, params=params or {}))

    def post(
        self,
        path: str,
        json_body: Mapping[str, JsonValue] | list[JsonValue] | str | None = None,
        params: Mapping[str, ParamValue] | None = None,
    ) -> JsonValue:
        """Send a POST request to the Jira REST API."""
        self._rate_limit()
        return self._handle_response(self._http.post(path, json=json_body, params=params or {}))

    def put(
        self,
        path: str,
        json_body: Mapping[str, JsonValue] | None = None,
        params: Mapping[str, ParamValue] | None = None,
    ) -> JsonValue:
        """Send a PUT request to the Jira REST API."""
        self._rate_limit()
        return self._handle_response(self._http.put(path, json=json_body, params=params or {}))

    def delete(
        self,
        path: str,
        params: Mapping[str, ParamValue] | None = None,
    ) -> JsonValue:
        """Send a DELETE request to the Jira REST API."""
        self._rate_limit()
        return self._handle_response(self._http.delete(path, params=params or {}))

    def post_multipart(
        self,
        path: str,
        file_path: str,
        params: Mapping[str, ParamValue] | None = None,
    ) -> JsonValue:
        """Send a multipart/form-data POST (for attachments)."""
        self._rate_limit()
        with Path(file_path).open("rb") as f:
            return self._handle_response(
                self._http.post(
                    path,
                    files={"file": f},
                    headers={"X-Atlassian-Token": "no-check"},
                    params=params or {},
                )
            )


_cached_client: JiraClient | None = None


def get_client() -> JiraClient:
    """Return a singleton JiraClient, creating it on first call."""
    global _cached_client
    if _cached_client is None:
        _cached_client = JiraClient(load_config())
    return _cached_client
