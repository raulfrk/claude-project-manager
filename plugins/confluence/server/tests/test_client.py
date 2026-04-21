"""Tests for ConfluenceClient construction + HTTP behavior."""

from __future__ import annotations

import base64

import httpx
import pytest
import respx

from server.lib.client import ConfluenceClient, get_client
from server.lib.config import ConfluenceConfig
from server.lib.errors import (
    AuthError,
    ConfigError,
    NotFoundError,
    RateLimitError,
    ServerError,
)


def _cloud_cfg(**overrides) -> ConfluenceConfig:
    return ConfluenceConfig(
        deployment="auto",
        base_url="https://acme.atlassian.net",
        email="u@example.com",
        api_token="tok",
        **overrides,
    )


def _server_cfg(**overrides) -> ConfluenceConfig:
    return ConfluenceConfig(
        deployment="auto",
        base_url="https://conf.example.com",
        personal_access_token="pat",
        **overrides,
    )


def test_auto_detects_cloud() -> None:
    client = ConfluenceClient(_cloud_cfg())
    assert client.effective_deployment == "cloud"
    assert client.api_base == "https://acme.atlassian.net/wiki/rest/api"


def test_auto_detects_server() -> None:
    client = ConfluenceClient(_server_cfg())
    assert client.effective_deployment == "server"
    assert client.api_base == "https://conf.example.com/rest/api"


def test_explicit_deployment_overrides_detection() -> None:
    cfg = ConfluenceConfig(
        deployment="server",
        base_url="https://acme.atlassian.net",  # normally cloud
        personal_access_token="pat",
    )
    client = ConfluenceClient(cfg)
    assert client.effective_deployment == "server"


def test_cloud_missing_creds_raises() -> None:
    cfg = ConfluenceConfig(
        deployment="cloud",
        base_url="https://acme.atlassian.net",
    )
    with pytest.raises(ConfigError, match=r"email.*api_token"):
        ConfluenceClient(cfg)


def test_server_missing_pat_raises() -> None:
    cfg = ConfluenceConfig(
        deployment="server",
        base_url="https://conf.example.com",
    )
    with pytest.raises(ConfigError, match="personal_access_token"):
        ConfluenceClient(cfg)


def test_cloud_auth_header_is_basic() -> None:
    client = ConfluenceClient(_cloud_cfg())
    expected = base64.b64encode(b"u@example.com:tok").decode()
    assert client.auth_header == f"Basic {expected}"


def test_server_auth_header_is_bearer() -> None:
    client = ConfluenceClient(_server_cfg())
    assert client.auth_header == "Bearer pat"


@respx.mock
def test_get_success() -> None:
    client = ConfluenceClient(_server_cfg())
    respx.get("https://conf.example.com/rest/api/space").mock(
        return_value=httpx.Response(200, json={"results": []})
    )

    data = client.get("/space", params={})

    assert data == {"results": []}


@respx.mock
def test_get_404_raises_not_found() -> None:
    client = ConfluenceClient(_server_cfg())
    respx.get("https://conf.example.com/rest/api/content/nope").mock(
        return_value=httpx.Response(404, json={"message": "not found"})
    )

    with pytest.raises(NotFoundError):
        client.get("/content/nope", params={})


@respx.mock
def test_get_401_raises_auth_error() -> None:
    client = ConfluenceClient(_server_cfg())
    respx.get("https://conf.example.com/rest/api/space").mock(
        return_value=httpx.Response(401, json={"message": "bad auth"})
    )

    with pytest.raises(AuthError):
        client.get("/space", params={})


@respx.mock
def test_get_500_raises_server_error() -> None:
    client = ConfluenceClient(_server_cfg())
    respx.get("https://conf.example.com/rest/api/space").mock(
        return_value=httpx.Response(500, text="internal")
    )

    with pytest.raises(ServerError):
        client.get("/space", params={})


@respx.mock
def test_get_429_retries_honoring_retry_after() -> None:
    client = ConfluenceClient(_server_cfg())
    route = respx.get("https://conf.example.com/rest/api/space")
    route.side_effect = [
        httpx.Response(429, headers={"Retry-After": "1"}),
        httpx.Response(200, json={"results": []}),
    ]

    data = client.get("/space", params={})

    assert data == {"results": []}
    assert route.call_count == 2


@respx.mock
def test_get_429_after_3_retries_raises_rate_limit() -> None:
    client = ConfluenceClient(_server_cfg())
    respx.get("https://conf.example.com/rest/api/space").mock(
        return_value=httpx.Response(429, headers={"Retry-After": "1"})
    )

    with pytest.raises(RateLimitError):
        client.get("/space", params={})


def test_get_client_is_cached(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    cfg_path = tmp_path / "confluence.yaml"
    cfg_path.write_text(
        "deployment: server\nbase_url: https://x.example.com\npersonal_access_token: pat\n"
    )
    monkeypatch.setenv("CONFLUENCE_CONFIG", str(cfg_path))

    import server.lib.client as mod

    mod._cached_client = None  # reset

    a = get_client()
    b = get_client()
    assert a is b
