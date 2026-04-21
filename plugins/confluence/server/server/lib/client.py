"""Confluence HTTP client — deployment detection, auth, retry, rate limit."""

from __future__ import annotations

import base64
import time
from typing import Any
from urllib.parse import urlparse

import httpx

from server.lib.config import ConfluenceConfig, load_config
from server.lib.errors import (
    AuthError,
    ConfigError,
    NotFoundError,
    RateLimitError,
    ServerError,
    SpaceNotAllowedError,
)
from server.lib.ratelimit import TokenBucket

_CLOUD_HOST_SUFFIX = ".atlassian.net"
_MAX_RETRIES = 3


class ConfluenceClient:
    def __init__(self, config: ConfluenceConfig) -> None:
        self._config = config
        self.effective_deployment = self._detect_deployment(config)
        self._validate_creds()
        self.auth_header = self._assemble_auth_header()
        self.api_base = self._resolve_api_base()
        self._http = httpx.Client(
            base_url=self.api_base,
            headers={
                "Authorization": self.auth_header,
                "Accept": "application/json",
            },
            timeout=config.timeout_seconds,
        )
        self._bucket = TokenBucket(
            capacity=config.rate_limit_per_10s,
            refill_seconds=10.0,
        )

    @staticmethod
    def _detect_deployment(cfg: ConfluenceConfig) -> str:
        if cfg.deployment in ("cloud", "server"):
            return cfg.deployment
        host = urlparse(cfg.base_url).hostname or ""
        if host.endswith(_CLOUD_HOST_SUFFIX):
            return "cloud"
        return "server"

    def _validate_creds(self) -> None:
        cfg = self._config
        if self.effective_deployment == "cloud":
            if not cfg.email or not cfg.api_token:
                raise ConfigError("Cloud deployment requires email + api_token")
        elif self.effective_deployment == "server" and not cfg.personal_access_token:
            raise ConfigError("Server deployment requires personal_access_token")

    def _assemble_auth_header(self) -> str:
        cfg = self._config
        if self.effective_deployment == "cloud":
            raw = f"{cfg.email}:{cfg.api_token}".encode()
            return f"Basic {base64.b64encode(raw).decode()}"
        return f"Bearer {cfg.personal_access_token}"

    def _resolve_api_base(self) -> str:
        if self.effective_deployment == "cloud":
            return f"{self._config.base_url}/wiki/rest/api"
        return f"{self._config.base_url}/rest/api"

    def get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET with rate limit, retry, and typed error translation."""
        for attempt in range(_MAX_RETRIES):
            self._bucket.acquire()
            resp = self._http.get(path, params=params)
            if resp.status_code == 200:
                return resp.json()  # type: ignore[no-any-return]
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", "1"))
                if attempt == _MAX_RETRIES - 1:
                    raise RateLimitError(
                        f"Rate limited after {_MAX_RETRIES} retries",
                        retry_after=retry_after,
                    )
                time.sleep(retry_after)
                continue
            if resp.status_code in (401, 403):
                raise AuthError(f"Auth failed: {resp.status_code} {resp.text}")
            if resp.status_code == 404:
                raise NotFoundError(f"Not found: {resp.status_code} {resp.text}")
            if resp.status_code >= 500:
                raise ServerError(f"Server error: {resp.status_code} {resp.text}")
            raise ServerError(f"Unexpected response: {resp.status_code} {resp.text}")
        # Unreachable
        raise RateLimitError("Exhausted retries")

    def check_space_allowed(self, space_key: str) -> None:
        """Raise SpaceNotAllowedError if allowed_spaces non-empty and key not in it."""
        if self._config.allowed_spaces and space_key not in self._config.allowed_spaces:
            raise SpaceNotAllowedError(space_key)

    @property
    def config(self) -> ConfluenceConfig:
        return self._config


_cached_client: ConfluenceClient | None = None


def get_client() -> ConfluenceClient:
    global _cached_client
    if _cached_client is None:
        _cached_client = ConfluenceClient(load_config())
    return _cached_client
