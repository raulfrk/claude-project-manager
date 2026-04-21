"""Shared test fixtures."""

from __future__ import annotations

import pytest

from server.lib.client import ConfluenceClient
from server.lib.config import ConfluenceConfig


@pytest.fixture()
def cloud_config() -> ConfluenceConfig:
    return ConfluenceConfig(
        deployment="cloud",
        base_url="https://acme.atlassian.net",
        email="u@example.com",
        api_token="tok",
    )


@pytest.fixture()
def server_config() -> ConfluenceConfig:
    return ConfluenceConfig(
        deployment="server",
        base_url="https://conf.example.com",
        personal_access_token="pat",
    )


@pytest.fixture()
def cloud_client(cloud_config, monkeypatch: pytest.MonkeyPatch) -> ConfluenceClient:
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    return ConfluenceClient(cloud_config)


@pytest.fixture()
def server_client(server_config, monkeypatch: pytest.MonkeyPatch) -> ConfluenceClient:
    for var in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        monkeypatch.delenv(var, raising=False)
    return ConfluenceClient(server_config)
