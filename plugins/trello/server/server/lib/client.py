"""Trello REST API client with rate limiting."""

from __future__ import annotations

import time
from collections import deque
from typing import Any

import httpx

from server.lib.config import TrelloConfig, load_config

BASE_URL = "https://api.trello.com/1"


class TrelloClient:
    """HTTP client for the Trello REST API."""

    def __init__(self, config: TrelloConfig) -> None:
        self._config = config
        self._http = httpx.Client(base_url=BASE_URL, timeout=30)
        self._request_timestamps: deque[float] = deque()

    def _auth_params(self) -> dict[str, str]:
        return {"key": self._config.api_key, "token": self._config.token}

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
        msg = f"Trello API error {resp.status_code}: {resp.text}"
        raise RuntimeError(msg)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
        """Send a GET request to the Trello API."""
        self._rate_limit()
        merged = {**self._auth_params(), **(params or {})}
        return self._handle_response(self._http.get(path, params=merged))

    def post(  # noqa: ANN401
        self,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Send a POST request to the Trello API."""
        self._rate_limit()
        merged = {**self._auth_params(), **(params or {})}
        return self._handle_response(self._http.post(path, params=merged, json=json))

    def put(  # noqa: ANN401
        self,
        path: str,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
    ) -> Any:
        """Send a PUT request to the Trello API."""
        self._rate_limit()
        merged = {**self._auth_params(), **(params or {})}
        return self._handle_response(self._http.put(path, params=merged, json=json))

    def delete(self, path: str, params: dict[str, Any] | None = None) -> Any:  # noqa: ANN401
        """Send a DELETE request to the Trello API."""
        self._rate_limit()
        merged = {**self._auth_params(), **(params or {})}
        return self._handle_response(self._http.delete(path, params=merged))


_cached_client: TrelloClient | None = None


def get_client() -> TrelloClient:
    """Return a singleton TrelloClient, creating it on first call."""
    global _cached_client  # noqa: PLW0603
    if _cached_client is None:
        _cached_client = TrelloClient(load_config())
    return _cached_client
