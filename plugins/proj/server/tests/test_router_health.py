"""Tests for server.lib.router_health.check_router_reachable."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

from server.lib import router_health
from server.lib.router_health import (
    _DETAIL_ENUM,
    check_router_reachable,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove HOOKS_HEALTH_CHECK env var so tests start clean."""
    monkeypatch.delenv("HOOKS_HEALTH_CHECK", raising=False)
    monkeypatch.delenv("HOOK_TRANSPORT", raising=False)


@pytest.fixture(autouse=True)
def _isolate_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Redirect _cache_path() to a tmp file so tests never touch real cache."""
    cache_file = tmp_path / "health.cache"

    def _fake_cache_path() -> Path:
        return cache_file

    monkeypatch.setattr(router_health, "_cache_path", _fake_cache_path)
    return cache_file


def _mock_httpx_post(
    monkeypatch: pytest.MonkeyPatch,
    post_fn: Callable[..., Any],
) -> None:
    """Patch httpx.AsyncClient.post to call post_fn."""
    monkeypatch.setattr(
        httpx.AsyncClient,
        "post",
        post_fn,
    )


def _mock_resolver(
    monkeypatch: pytest.MonkeyPatch,
    side_effect: Any = None,
    return_value: Any = None,
) -> None:
    """Patch _resolve_hooks_transport used by router_health."""
    if side_effect is not None:
        monkeypatch.setattr(
            router_health,
            "_resolve_hooks_transport",
            lambda port: (_ for _ in ()).throw(side_effect)  # type: ignore[misc]
            if isinstance(side_effect, BaseException)
            else side_effect(port),
        )
    else:
        monkeypatch.setattr(
            router_health,
            "_resolve_hooks_transport",
            lambda port: return_value,
        )


class _FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


class _FakeTransport(httpx.AsyncBaseTransport):
    async def handle_async_request(
        self, request: httpx.Request
    ) -> httpx.Response:  # pragma: no cover
        return httpx.Response(200)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """200 OK → (True, '')."""
    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", _FakeTransport()))

    async def _post(self: Any, url: str, json: Any = None) -> _FakeResponse:
        return _FakeResponse(200)

    _mock_httpx_post(monkeypatch, _post)
    ok, detail = await check_router_reachable()
    assert ok is True
    assert detail == ""


@pytest.mark.asyncio
async def test_missing_registry_filenotfound(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(port: int) -> Any:
        raise FileNotFoundError("no registry")

    monkeypatch.setattr(router_health, "_resolve_hooks_transport", _raise)
    ok, detail = await check_router_reachable()
    assert ok is False
    assert detail == _DETAIL_ENUM["missing_registry"]


@pytest.mark.asyncio
async def test_missing_registry_transport_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", None))
    ok, detail = await check_router_reachable()
    assert ok is False
    assert detail == _DETAIL_ENUM["missing_registry"]


@pytest.mark.asyncio
async def test_connect_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", _FakeTransport()))

    async def _post(self: Any, url: str, json: Any = None) -> _FakeResponse:
        raise httpx.ConnectError("dead socket")

    _mock_httpx_post(monkeypatch, _post)
    ok, detail = await check_router_reachable(retry_delay=0.0)
    assert ok is False
    assert detail == _DETAIL_ENUM["connect_error"]


@pytest.mark.asyncio
async def test_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", _FakeTransport()))

    async def _post(self: Any, url: str, json: Any = None) -> _FakeResponse:
        raise httpx.ReadTimeout("timed out")

    _mock_httpx_post(monkeypatch, _post)
    ok, detail = await check_router_reachable(retry_delay=0.0)
    assert ok is False
    assert detail == _DETAIL_ENUM["timeout"]


@pytest.mark.asyncio
async def test_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", _FakeTransport()))

    async def _post(self: Any, url: str, json: Any = None) -> _FakeResponse:
        return _FakeResponse(500)

    _mock_httpx_post(monkeypatch, _post)
    ok, detail = await check_router_reachable(retry_delay=0.0)
    assert ok is False
    assert detail == _DETAIL_ENUM["http_error"]


@pytest.mark.asyncio
async def test_retry_success_on_second(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", _FakeTransport()))
    calls: list[int] = []

    async def _post(self: Any, url: str, json: Any = None) -> _FakeResponse:
        calls.append(1)
        if len(calls) == 1:
            raise httpx.ConnectError("first fail")
        return _FakeResponse(200)

    _mock_httpx_post(monkeypatch, _post)
    ok, detail = await check_router_reachable(retry_delay=0.0)
    assert ok is True
    assert detail == ""
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_retry_both_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", _FakeTransport()))
    calls: list[int] = []

    async def _post(self: Any, url: str, json: Any = None) -> _FakeResponse:
        calls.append(1)
        raise httpx.ConnectError("dead")

    _mock_httpx_post(monkeypatch, _post)
    ok, detail = await check_router_reachable(retry_delay=0.0)
    assert ok is False
    assert detail == _DETAIL_ENUM["connect_error"]
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_env_opt_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOOKS_HEALTH_CHECK", "0")
    # Even if resolver would fail, env opt-out short-circuits to success.
    ok, detail = await check_router_reachable()
    assert ok is True
    assert detail == ""


@pytest.mark.asyncio
async def test_cache_hit(monkeypatch: pytest.MonkeyPatch, _isolate_cache: Path) -> None:
    _isolate_cache.write_text(
        json.dumps({"ts": time.time(), "ok": False, "detail": "cached detail"})
    )
    # Resolver will never be called because cache hit short-circuits.
    called: list[int] = []

    def _resolver(port: int) -> Any:
        called.append(1)
        return ("http://localhost/hook", _FakeTransport())

    monkeypatch.setattr(router_health, "_resolve_hooks_transport", _resolver)
    ok, detail = await check_router_reachable()
    assert ok is False
    assert detail == "cached detail"
    assert called == []


@pytest.mark.asyncio
async def test_cache_expired(monkeypatch: pytest.MonkeyPatch, _isolate_cache: Path) -> None:
    _isolate_cache.write_text(json.dumps({"ts": time.time() - 120.0, "ok": False, "detail": "old"}))
    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", _FakeTransport()))

    async def _post(self: Any, url: str, json: Any = None) -> _FakeResponse:
        return _FakeResponse(200)

    _mock_httpx_post(monkeypatch, _post)
    ok, detail = await check_router_reachable()
    assert ok is True
    assert detail == ""


@pytest.mark.asyncio
async def test_cache_corrupt(monkeypatch: pytest.MonkeyPatch, _isolate_cache: Path) -> None:
    _isolate_cache.write_text("not json {{{")
    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", _FakeTransport()))

    async def _post(self: Any, url: str, json: Any = None) -> _FakeResponse:
        return _FakeResponse(200)

    _mock_httpx_post(monkeypatch, _post)
    ok, detail = await check_router_reachable()
    assert ok is True
    assert detail == ""


@pytest.mark.asyncio
async def test_cache_different_ppid(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Cache file includes ppid — different ppid must not collide."""
    # Restore real _cache_path but redirect its getppid.
    cache_a = tmp_path / "claude-cpm-health-111.cache"
    cache_a.write_text(json.dumps({"ts": time.time(), "ok": False, "detail": "ppid111"}))

    monkeypatch.setattr(os, "getppid", lambda: 222)

    def _fake_path() -> Path:
        return tmp_path / f"claude-cpm-health-{os.getppid()}.cache"

    monkeypatch.setattr(router_health, "_cache_path", _fake_path)

    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", _FakeTransport()))

    async def _post(self: Any, url: str, json: Any = None) -> _FakeResponse:
        return _FakeResponse(200)

    _mock_httpx_post(monkeypatch, _post)
    ok, detail = await check_router_reachable()
    # Must probe fresh (cache miss for ppid 222) and return success.
    assert ok is True
    assert detail == ""


@pytest.mark.asyncio
async def test_tcp_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HOOK_TRANSPORT=tcp path uses TCP target — simulated via resolver return."""
    monkeypatch.setenv("HOOK_TRANSPORT", "tcp")
    tcp_transport = httpx.AsyncHTTPTransport()
    _mock_resolver(monkeypatch, return_value=("http://127.0.0.1:19100/hook", tcp_transport))

    async def _post(self: Any, url: str, json: Any = None) -> _FakeResponse:
        assert url == "http://127.0.0.1:19100/hook"
        return _FakeResponse(200)

    _mock_httpx_post(monkeypatch, _post)
    ok, detail = await check_router_reachable()
    assert ok is True
    assert detail == ""


@pytest.mark.asyncio
async def test_malformed_registry_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Resolver returns (url, None) for empty registry → missing_registry detail."""
    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", None))
    ok, detail = await check_router_reachable(retry_delay=0.0)
    assert ok is False
    assert detail == _DETAIL_ENUM["missing_registry"]


@pytest.mark.asyncio
async def test_malformed_registry_permission_denied(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(port: int) -> Any:
        raise PermissionError("denied")

    monkeypatch.setattr(router_health, "_resolve_hooks_transport", _raise)
    ok, detail = await check_router_reachable(retry_delay=0.0)
    assert ok is False
    assert detail == _DETAIL_ENUM["missing_registry"]


@pytest.mark.asyncio
async def test_unknown_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Arbitrary post exception → unknown detail."""
    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", _FakeTransport()))

    async def _post(self: Any, url: str, json: Any = None) -> _FakeResponse:
        raise RuntimeError("surprise")

    _mock_httpx_post(monkeypatch, _post)
    ok, detail = await check_router_reachable(retry_delay=0.0)
    assert ok is False
    assert detail == _DETAIL_ENUM["unknown"]


@pytest.mark.asyncio
async def test_write_cache_after_probe(
    monkeypatch: pytest.MonkeyPatch, _isolate_cache: Path
) -> None:
    """After a successful probe, cache file exists with ok=True."""
    _mock_resolver(monkeypatch, return_value=("http://localhost/hook", _FakeTransport()))

    async def _post(self: Any, url: str, json: Any = None) -> _FakeResponse:
        return _FakeResponse(200)

    _mock_httpx_post(monkeypatch, _post)
    await check_router_reachable()
    assert _isolate_cache.exists()
    obj = json.loads(_isolate_cache.read_text())
    assert obj["ok"] is True
    assert obj["detail"] == ""
