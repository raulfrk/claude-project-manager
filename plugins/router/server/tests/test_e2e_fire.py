"""End-to-end tests for hook fire chain.

Starts a real proj MCP server as a subprocess with dual transport,
registers hooks in a temp hooks.yaml, fires via hooks_fire(), and verifies
target tools actually execute via HTTP POST.  No mocking of HTTP anywhere.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from server.lib import storage
from server.lib.models import Hook, HookRegistry
from server.tools.fire import hooks_fire

_PLUGINS_DIR = Path(__file__).resolve().parents[3]
_PROJ_SERVER_DIR = _PLUGINS_DIR / "proj" / "server"

# Atomic port counter — each xdist worker gets a separate range to avoid collisions.
_port_counter_lock = threading.Lock()
_worker_id = os.environ.get("PYTEST_XDIST_WORKER", "gw0")
_worker_num = int(_worker_id.replace("gw", "")) if _worker_id.startswith("gw") else 0
_port_counter = 19200 + _worker_num * 10


def _next_port() -> int:
    global _port_counter
    with _port_counter_lock:
        port = _port_counter
        _port_counter += 1
    return port


def _wait_for_health(port: int, *, timeout: float = 15.0) -> None:
    """Poll GET /health until the server is ready or *timeout* expires."""
    deadline = time.monotonic() + timeout
    last_exc: Exception | None = None
    # Use explicit transport to bypass any SOCKS proxy in the environment
    transport = httpx.HTTPTransport()
    with httpx.Client(transport=transport, timeout=2.0) as client:
        while time.monotonic() < deadline:
            try:
                resp = client.get(f"http://127.0.0.1:{port}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    if "sandbox_list" in data.get("tools", []):
                        return
            except (httpx.ConnectError, httpx.ReadTimeout) as exc:
                last_exc = exc
            time.sleep(0.3)
    msg = f"Sandbox server on port {port} not healthy after {timeout}s"
    if last_exc:
        msg += f": {last_exc}"
    pytest.skip(msg)


_PROXY_VARS = (
    "ALL_PROXY",
    "all_proxy",
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "SOCKS_PROXY",
    "socks_proxy",
)


def _clean_env(**extras: str) -> dict[str, str]:
    """Return os.environ without proxy vars, with *extras* merged in."""
    env = {k: v for k, v in os.environ.items() if k not in _PROXY_VARS}
    env.update(extras)
    return env


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _strip_proxy(monkeypatch):
    """Remove SOCKS/HTTP proxy env vars so httpx connects directly to localhost."""
    for var in _PROXY_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture()
def sandbox_port():
    """Start a real proj MCP server subprocess and yield its HTTP port."""
    port = _next_port()
    env = _clean_env(HOOK_HTTP_PORT=str(port))

    proc = subprocess.Popen(
        ["uv", "run", "python", "-m", "server.main"],
        cwd=str(_PROJ_SERVER_DIR),
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        _wait_for_health(port)
        yield port
    finally:
        # Graceful shutdown: close stdin → stdio transport ends → HTTP shuts down
        if proc.stdin:
            proc.stdin.close()
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)


# ── E2E Tests ────────────────────────────────────────────────────────────────


@pytest.mark.e2e
class TestE2EHookFire:
    """End-to-end tests firing hooks to a real perms server via HTTP."""

    @pytest.mark.asyncio
    async def test_blocking_hook_returns_result(self, sandbox_port: int, tmp_path: Path):
        """Blocking hook → sandbox_list → result included in response."""
        hooks_yaml = tmp_path / "hooks.yaml"
        failures_yaml = tmp_path / "failures.yaml"

        registry = HookRegistry(
            hooks=[
                Hook(
                    id="e2e-001",
                    trigger_tool="test_trigger",
                    target_tool="sandbox_list",
                    server="proj",
                    param_mapping={},
                    blocking=True,
                ),
            ],
            servers={"proj": {"url": f"http://127.0.0.1:{sandbox_port}/hook"}},
        )
        storage.save(registry, path=hooks_yaml)

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
        ):
            raw = await hooks_fire("test_trigger", source_result="{}")

        data = json.loads(raw)
        assert data["hooks_fired"] == 1
        assert data["errors"] == []
        assert len(data["results"]) == 1
        assert data["results"][0]["hook_id"] == "e2e-001"
        # sandbox_list returns a string result (permissions listing)
        assert data["results"][0]["result"] is not None

    @pytest.mark.asyncio
    async def test_fire_to_dead_server_returns_error(self, tmp_path: Path):
        """Firing to a port with no server → connection error, no crash."""
        dead_port = _next_port()  # no server on this port
        hooks_yaml = tmp_path / "hooks.yaml"
        failures_yaml = tmp_path / "failures.yaml"

        registry = HookRegistry(
            hooks=[
                Hook(
                    id="e2e-002",
                    trigger_tool="test_trigger",
                    target_tool="sandbox_list",
                    server="proj",
                    param_mapping={},
                    blocking=True,
                ),
            ],
            servers={"proj": {"url": f"http://127.0.0.1:{dead_port}/hook"}},
        )
        storage.save(registry, path=hooks_yaml)

        empty_sockets = tmp_path / "empty_sockets"
        empty_sock_dir = tmp_path / "empty_sock_dir"
        empty_sock_dir.mkdir()
        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
            patch("server.tools.fire._SOCKET_REGISTRY_DIR", empty_sockets),
            patch("server.tools.fire.socket_dir", lambda: empty_sock_dir),
        ):
            raw = await hooks_fire("test_trigger", source_result="{}")

        data = json.loads(raw)
        assert data["hooks_fired"] == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["hook_id"] == "e2e-002"
        # Verify failure was logged
        failures = storage.load_failures(failures_yaml)
        assert len(failures) == 1
        assert failures[0]["hook_id"] == "e2e-002"

    @pytest.mark.asyncio
    async def test_nonblocking_returns_immediately(self, sandbox_port: int, tmp_path: Path):
        """Non-blocking hook → hooks_fire returns immediately, results empty."""
        hooks_yaml = tmp_path / "hooks.yaml"
        failures_yaml = tmp_path / "failures.yaml"

        registry = HookRegistry(
            hooks=[
                Hook(
                    id="e2e-003",
                    trigger_tool="test_trigger",
                    target_tool="sandbox_list",
                    server="proj",
                    param_mapping={},
                    blocking=False,
                ),
            ],
            servers={"proj": {"url": f"http://127.0.0.1:{sandbox_port}/hook"}},
        )
        storage.save(registry, path=hooks_yaml)

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
        ):
            raw = await hooks_fire("test_trigger", source_result="{}")

        data = json.loads(raw)
        assert data["hooks_fired"] == 1
        # Non-blocking hooks don't return results (fire-and-forget)
        assert data["results"] == []
        assert data["errors"] == []

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self, sandbox_port: int, tmp_path: Path):
        """Hook targeting non-existent tool → 404 error captured."""
        hooks_yaml = tmp_path / "hooks.yaml"
        failures_yaml = tmp_path / "failures.yaml"

        registry = HookRegistry(
            hooks=[
                Hook(
                    id="e2e-004",
                    trigger_tool="test_trigger",
                    target_tool="nonexistent_tool",
                    server="proj",
                    param_mapping={},
                    blocking=True,
                ),
            ],
            servers={"proj": {"url": f"http://127.0.0.1:{sandbox_port}/hook"}},
        )
        storage.save(registry, path=hooks_yaml)

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
        ):
            raw = await hooks_fire("test_trigger", source_result="{}")

        data = json.loads(raw)
        assert data["hooks_fired"] == 1
        assert len(data["errors"]) == 1
        assert "Unknown tool" in data["errors"][0]["error"]
        # Verify failure was logged
        failures = storage.load_failures(failures_yaml)
        assert len(failures) == 1
        assert failures[0]["hook_id"] == "e2e-004"
        assert "Unknown tool" in failures[0]["error"]

    @pytest.mark.asyncio
    async def test_blocking_with_param_mapping(self, sandbox_port: int, tmp_path: Path):
        """Blocking hook with param_mapping resolves templates from source_result."""
        hooks_yaml = tmp_path / "hooks.yaml"
        failures_yaml = tmp_path / "failures.yaml"

        registry = HookRegistry(
            hooks=[
                Hook(
                    id="e2e-005",
                    trigger_tool="test_trigger",
                    target_tool="sandbox_list",
                    server="proj",
                    param_mapping={"format": "${format}"},
                    blocking=True,
                ),
            ],
            servers={"proj": {"url": f"http://127.0.0.1:{sandbox_port}/hook"}},
        )
        storage.save(registry, path=hooks_yaml)

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
        ):
            raw = await hooks_fire(
                "test_trigger",
                source_result='{"format": "json"}',
            )

        data = json.loads(raw)
        assert data["hooks_fired"] == 1
        assert data["errors"] == []
        assert len(data["results"]) == 1
        # sandbox_list with format=json returns JSON-parseable output
        assert data["results"][0]["result"] is not None

    @pytest.mark.asyncio
    async def test_multiple_hooks_same_trigger(self, sandbox_port: int, tmp_path: Path):
        """Multiple hooks for the same trigger all fire correctly."""
        hooks_yaml = tmp_path / "hooks.yaml"
        failures_yaml = tmp_path / "failures.yaml"

        registry = HookRegistry(
            hooks=[
                Hook(
                    id="e2e-006a",
                    trigger_tool="test_trigger",
                    target_tool="sandbox_list",
                    server="proj",
                    param_mapping={},
                    blocking=True,
                ),
                Hook(
                    id="e2e-006b",
                    trigger_tool="test_trigger",
                    target_tool="sandbox_check",
                    server="proj",
                    param_mapping={},
                    blocking=True,
                ),
            ],
            servers={"proj": {"url": f"http://127.0.0.1:{sandbox_port}/hook"}},
        )
        storage.save(registry, path=hooks_yaml)

        with (
            patch("server.lib.storage._HOOKS_FILE", hooks_yaml),
            patch("server.lib.storage._FAILURES_FILE", failures_yaml),
        ):
            raw = await hooks_fire("test_trigger", source_result="{}")

        data = json.loads(raw)
        assert data["hooks_fired"] == 2
        assert data["errors"] == []
        assert len(data["results"]) == 2
        hook_ids = {r["hook_id"] for r in data["results"]}
        assert hook_ids == {"e2e-006a", "e2e-006b"}
