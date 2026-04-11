"""Async probe for router MCP server reachability."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path

import httpx
from hook_dispatch.dispatch import _resolve_hooks_transport

_CACHE_TTL_S = 60.0
_PROBE_TIMEOUT_S = 2.0
_RETRY_DELAY_S = 0.5
_DEFAULT_HOOKS_PORT = 19100

_DETAIL_ENUM = {
    "missing_registry": "restart Claude Code (router registry not found)",
    "connect_error": "router socket dead — restart Claude Code",
    "timeout": "router not responding — check router MCP server logs",
    "http_error": "router responded with error — check router MCP server logs",
    "unknown": "router probe failed — check router MCP server logs",
}


def _cache_path() -> Path:
    return Path(f"/tmp/claude-cpm-health-{os.getppid()}.cache")  # noqa: S108


def _read_cache() -> tuple[bool, str] | None:
    try:
        raw = _cache_path().read_text()
        obj = json.loads(raw)
        if time.time() - obj["ts"] < _CACHE_TTL_S:
            return bool(obj["ok"]), str(obj["detail"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        pass
    return None


def _write_cache(ok: bool, detail: str) -> None:
    try:
        cache = _cache_path()
        tmp = cache.with_suffix(".tmp")
        tmp.write_text(json.dumps({"ts": time.time(), "ok": ok, "detail": detail}))
        tmp.replace(cache)
        cache.chmod(0o600)
    except OSError:
        pass  # cache writes are best-effort


async def _probe_once(timeout: float) -> tuple[bool, str]:
    try:
        target, transport = _resolve_hooks_transport(_DEFAULT_HOOKS_PORT)
    except FileNotFoundError:
        return False, _DETAIL_ENUM["missing_registry"]
    except Exception:
        return False, _DETAIL_ENUM["missing_registry"]
    if transport is None:
        return False, _DETAIL_ENUM["missing_registry"]
    try:
        async with httpx.AsyncClient(timeout=timeout, transport=transport) as client:
            response = await client.post(target, json={"tool": "router_list_tool", "params": {}})
            if response.status_code == 200:
                return True, ""
            return False, _DETAIL_ENUM["http_error"]
    except httpx.ConnectError:
        return False, _DETAIL_ENUM["connect_error"]
    except (TimeoutError, httpx.TimeoutException):
        return False, _DETAIL_ENUM["timeout"]
    except Exception:
        return False, _DETAIL_ENUM["unknown"]


async def check_router_reachable(
    timeout: float = _PROBE_TIMEOUT_S,
    retry_delay: float = _RETRY_DELAY_S,
    cache_ttl: float = _CACHE_TTL_S,
) -> tuple[bool, str]:
    """Probe router MCP socket; return (ok, detail).

    Honours HOOKS_HEALTH_CHECK=0 opt-out. Uses a per-parent-PID on-disk cache
    with a default 60s TTL. On failure, retries once after ``retry_delay``.
    ``detail`` is empty on success and an actionable fix suggestion on failure.
    """
    del cache_ttl  # reserved for future callers
    if os.environ.get("HOOKS_HEALTH_CHECK") == "0":
        return True, ""
    cached = _read_cache()
    if cached is not None:
        return cached
    ok, detail = await _probe_once(timeout)
    if not ok:
        await asyncio.sleep(retry_delay)
        ok, detail = await _probe_once(timeout)
    _write_cache(ok, detail)
    return ok, detail
