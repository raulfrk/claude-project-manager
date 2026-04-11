"""Tests for server.scripts.session_start_router_health.

The script is a thin subprocess-invokable wrapper around
``server.lib.router_health.check_router_reachable``. Tests run the script
through ``subprocess.run`` and inject a stub ``router_health`` module via a
``PYTHONPATH`` shim that overrides the real implementation.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "server" / "scripts" / "session_start_router_health.py"


def _make_stub(
    tmp_path: Path,
    *,
    ok: bool = True,
    detail: str = "",
    raise_exc: bool = False,
) -> Path:
    """Create a fake server.lib.router_health module that returns the given result."""
    shim_root = tmp_path / "shim"
    pkg = shim_root / "server" / "lib"
    pkg.mkdir(parents=True)
    (shim_root / "server" / "__init__.py").write_text("")
    (pkg / "__init__.py").write_text("")

    body = 'raise RuntimeError("helper crashed")' if raise_exc else f"return ({ok!r}, {detail!r})"

    module = textwrap.dedent(
        f"""
        async def check_router_reachable(*args, **kwargs):
            {body}
        """
    ).strip()
    (pkg / "router_health.py").write_text(module)
    return shim_root


def _run_script(
    shim_root: Path,
    *,
    env_overrides: dict[str, str] | None = None,
    isatty: bool = False,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    # Prepend the shim so it wins over the real server.lib.router_health.
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{shim_root}{os.pathsep}{existing}" if existing else str(shim_root)
    env.pop("HOOKS_HEALTH_CHECK", None)
    if env_overrides:
        env.update(env_overrides)

    # Simulate TTY attachment by routing stderr through a pty when isatty=True.
    if isatty:
        import pty

        master, slave = pty.openpty()
        proc = subprocess.Popen(
            [sys.executable, str(SCRIPT)],
            stdout=subprocess.PIPE,
            stderr=slave,
            env=env,
            text=True,
        )
        os.close(slave)
        # Read stderr from master fd until process exits.
        stderr_chunks: list[str] = []
        try:
            while True:
                try:
                    chunk = os.read(master, 4096).decode("utf-8", errors="replace")
                except OSError:
                    break
                if not chunk:
                    break
                stderr_chunks.append(chunk)
        finally:
            os.close(master)
        proc.wait(timeout=10)
        stdout = proc.stdout.read() if proc.stdout else ""
        return subprocess.CompletedProcess(
            args=proc.args,
            returncode=proc.returncode,
            stdout=stdout,
            stderr="".join(stderr_chunks),
        )

    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=10,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_silent_on_success(tmp_path: Path) -> None:
    shim = _make_stub(tmp_path, ok=True, detail="")
    result = _run_script(shim)
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_banner_on_failure(tmp_path: Path) -> None:
    shim = _make_stub(tmp_path, ok=False, detail="router socket dead — restart Claude Code")
    result = _run_script(shim)
    assert result.returncode == 0
    assert result.stdout == ""
    assert "Hook router unreachable" in result.stderr
    assert "router socket dead" in result.stderr
    assert "HOOKS_HEALTH_CHECK=0 to silence" in result.stderr


def test_ansi_on_tty(tmp_path: Path) -> None:
    shim = _make_stub(tmp_path, ok=False, detail="timeout detail")
    result = _run_script(shim, isatty=True)
    assert result.returncode == 0
    # ANSI red prefix and reset must be present when writing to a TTY.
    assert "\033[31m" in result.stderr
    assert "\033[0m" in result.stderr


def test_no_ansi_off_tty(tmp_path: Path) -> None:
    shim = _make_stub(tmp_path, ok=False, detail="timeout detail")
    result = _run_script(shim)
    assert result.returncode == 0
    assert "\033[31m" not in result.stderr
    assert "\033[0m" not in result.stderr
    assert "Hook router unreachable" in result.stderr


def test_env_opt_out_skips(tmp_path: Path) -> None:
    shim = _make_stub(tmp_path, ok=False, detail="would fail")
    result = _run_script(shim, env_overrides={"HOOKS_HEALTH_CHECK": "0"})
    assert result.returncode == 0
    # Opt-out skips the probe entirely — no banner.
    assert result.stderr == ""


def test_exception_in_helper_swallowed(tmp_path: Path) -> None:
    shim = _make_stub(tmp_path, raise_exc=True)
    result = _run_script(shim)
    # Exceptions must never crash the hook or fail the session.
    assert result.returncode == 0
    assert result.stdout == ""


def test_banner_text_exact(tmp_path: Path) -> None:
    shim = _make_stub(tmp_path, ok=False, detail="restart Claude Code (router registry not found)")
    result = _run_script(shim)
    assert result.returncode == 0
    expected = (
        "\u26a0 Hook router unreachable — todo/sync hooks will not fire this session"
        " (see: restart Claude Code (router registry not found);"
        " set HOOKS_HEALTH_CHECK=0 to silence)"
    )
    assert expected in result.stderr


def test_banner_has_no_pid_username_host(tmp_path: Path) -> None:
    """Banner must not leak pid/username/hostname (scrubbed by construction)."""
    shim = _make_stub(tmp_path, ok=False, detail="connect error")
    result = _run_script(shim)
    pid = str(os.getpid())
    user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    assert pid not in result.stderr
    if user:
        assert user not in result.stderr
    # Hostname should not appear in the banner text.
    import socket

    host = socket.gethostname()
    assert host not in result.stderr
