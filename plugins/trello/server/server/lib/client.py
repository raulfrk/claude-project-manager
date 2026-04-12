"""Trello REST API client with rate limiting."""

from __future__ import annotations

import time
from collections import deque
from typing import TYPE_CHECKING, cast

import httpx

from server.lib.config import TrelloConfig, load_config

if TYPE_CHECKING:
    from collections.abc import Mapping

BASE_URL = "https://api.trello.com/1"


class TrelloAPIError(RuntimeError):
    """Raised when the Trello API returns a non-success HTTP response."""

    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text
        super().__init__(f"Trello API error {status_code}: {text}")


# Recursive JSON value type — no Any needed.
JsonValue = str | int | float | bool | None | dict[str, "JsonValue"] | list["JsonValue"]

# HTTP query-param values are always flat scalars.
ParamValue = str | int | float | bool


class TrelloClient:
    """HTTP client for the Trello REST API."""

    def __init__(self, config: TrelloConfig) -> None:
        self._config = config
        self._http = httpx.Client(base_url=BASE_URL, timeout=30)
        self._request_timestamps: deque[float] = deque()

    def check_board_access(self, board_id: str) -> None:
        """Raise if board_id is not in the configured whitelist."""
        if not self._config.allowed_board_ids:
            raise RuntimeError(
                "No boards in whitelist. Run trello_init to configure allowed boards."
            )
        if board_id not in self._config.allowed_board_ids:
            raise RuntimeError(
                f"Board '{board_id}' not in whitelist. Allowed: {self._config.allowed_board_ids}"
            )

    def _auth_params(self) -> dict[str, str]:
        # Trello's REST API requires key/token as query parameters; there is no
        # header-based alternative.  This is a Trello API design constraint.
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

    MAX_RETRIES = 3
    DEFAULT_RETRY_AFTER = 5  # seconds

    def _handle_response(self, resp: httpx.Response) -> JsonValue:
        if resp.is_success:
            return cast("JsonValue", resp.json())
        raise TrelloAPIError(resp.status_code, resp.text)

    def _request(
        self,
        method: str,
        path: str,
        params: Mapping[str, ParamValue] | None = None,
        json: Mapping[str, JsonValue] | None = None,
    ) -> JsonValue:
        """Send an HTTP request with rate limiting and 429 retry."""
        self._rate_limit()
        merged: dict[str, ParamValue] = {
            **self._auth_params(),
            **(params or {}),
        }

        resp: httpx.Response | None = None
        for attempt in range(self.MAX_RETRIES + 1):
            resp = self._http.request(method, path, params=merged, json=json)
            if resp.status_code == 429 and attempt < self.MAX_RETRIES:
                try:
                    retry_after = int(resp.headers.get("Retry-After", self.DEFAULT_RETRY_AFTER))
                except (ValueError, TypeError):
                    retry_after = self.DEFAULT_RETRY_AFTER
                time.sleep(retry_after)
                continue
            return self._handle_response(resp)
        # Unreachable: range(MAX_RETRIES + 1) always has >= 1 iteration
        msg = "Retry loop completed without returning"
        raise RuntimeError(msg)

    def get(
        self,
        path: str,
        params: Mapping[str, ParamValue] | None = None,
    ) -> JsonValue:
        """Send a GET request to the Trello API."""
        return self._request("GET", path, params=params)

    def post(
        self,
        path: str,
        params: Mapping[str, ParamValue] | None = None,
        json: Mapping[str, JsonValue] | None = None,
    ) -> JsonValue:
        """Send a POST request to the Trello API."""
        return self._request("POST", path, params=params, json=json)

    def put(
        self,
        path: str,
        params: Mapping[str, ParamValue] | None = None,
        json: Mapping[str, JsonValue] | None = None,
    ) -> JsonValue:
        """Send a PUT request to the Trello API."""
        return self._request("PUT", path, params=params, json=json)

    def delete(
        self,
        path: str,
        params: Mapping[str, ParamValue] | None = None,
    ) -> JsonValue:
        """Send a DELETE request to the Trello API."""
        return self._request("DELETE", path, params=params)


_cached_client: TrelloClient | None = None


def get_client() -> TrelloClient:
    """Return a singleton TrelloClient, creating it on first call."""
    global _cached_client
    if _cached_client is None:
        _cached_client = TrelloClient(load_config())
    return _cached_client
