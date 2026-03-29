"""Todoist API v1 client with Bearer token auth and error handling."""

from __future__ import annotations

from typing import Any

import httpx

from server.lib.config import TodoistConfig, load_config

BASE_URL = "https://api.todoist.com/api/v1"


class TodoistClient:
    """HTTP client for the Todoist API v1."""

    def __init__(self, config: TodoistConfig) -> None:
        self._config = config
        self._http = httpx.Client(
            base_url=BASE_URL,
            headers={"Authorization": f"Bearer {config.api_token}"},
            timeout=30,
        )

    def _handle_response(self, resp: httpx.Response) -> Any:
        if resp.status_code == 401:
            raise RuntimeError("Todoist API error 401: Invalid API token")
        if resp.status_code == 429:
            retry_after = resp.headers.get("Retry-After", "60")
            raise RuntimeError(
                f"Todoist rate limited. Retry after {retry_after} seconds."
            )
        if resp.is_success:
            return resp.json() if resp.content else {"ok": True}
        raise RuntimeError(f"Todoist API error {resp.status_code}: {resp.text}")

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            resp = self._http.request(method, path, **kwargs)
        except httpx.TimeoutException:
            raise RuntimeError("Todoist API request timed out") from None
        return self._handle_response(resp)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Send a GET request to the Todoist API."""
        return self._request("GET", path, params=params)

    def post(self, path: str, json: dict[str, Any] | None = None) -> Any:
        """Send a POST request to the Todoist API."""
        return self._request("POST", path, json=json)

    def delete(self, path: str) -> Any:
        """Send a DELETE request to the Todoist API."""
        return self._request("DELETE", path)

    def close_task(self, task_id: str) -> Any:
        """Complete a task by ID (POST /tasks/{id}/close)."""
        return self.post(f"/tasks/{task_id}/close")

    def reopen_task(self, task_id: str) -> Any:
        """Reopen a completed task by ID (POST /tasks/{id}/reopen)."""
        return self.post(f"/tasks/{task_id}/reopen")


_cached_client: TodoistClient | None = None


def get_client() -> TodoistClient:
    """Return a singleton TodoistClient, creating it on first call."""
    global _cached_client
    if _cached_client is None:
        _cached_client = TodoistClient(load_config())
    return _cached_client
