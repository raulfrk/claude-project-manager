"""Tests for socket_path helper — single source of truth for tmp/socket paths."""

from __future__ import annotations

import socket as socket_mod
import tempfile
from pathlib import Path

import pytest

from hook_transport.socket_path import (
    legacy_socket_path,
    socket_dir,
    socket_glob,
    socket_path,
    tmp_dir,
)

# ── socket_dir / tmp_dir tests ──────────────────────────────────────────────


def test_socket_dir_honors_tempfile_gettempdir(monkeypatch: pytest.MonkeyPatch) -> None:
    """socket_dir() reflects tempfile.gettempdir() (which honors TMPDIR + platform default)."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: "/custom/tmp")
    assert socket_dir() == Path("/custom/tmp")


def test_socket_dir_default_is_tempfile_gettempdir(monkeypatch: pytest.MonkeyPatch) -> None:
    """When TMPDIR unset, socket_dir() falls back to whatever tempfile.gettempdir() returns.

    On Linux, that is typically "/tmp"; we don't hardcode the literal — we just
    assert that the helper agrees with the stdlib resolver.
    """
    monkeypatch.delenv("TMPDIR", raising=False)
    monkeypatch.delenv("TMP", raising=False)
    monkeypatch.delenv("TEMP", raising=False)
    # Force tempfile to recompute by clearing its cached tempdir.
    monkeypatch.setattr(tempfile, "tempdir", None)
    assert socket_dir() == Path(tempfile.gettempdir())


def test_tmp_dir_aliases_socket_dir() -> None:
    """tmp_dir() returns the same value as socket_dir() (currently aliased)."""
    assert tmp_dir() == socket_dir()


# ── socket_path tests ────────────────────────────────────────────────────────


def test_socket_path_format() -> None:
    """socket_path returns <socket_dir>/claude-cpm-<plugin>-<pid>.sock."""
    p = socket_path("router", 12345)
    assert p == socket_dir() / "claude-cpm-router-12345.sock"


def test_socket_path_uses_current_socket_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """socket_path uses the current socket_dir() at call time."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: "/elsewhere")
    p = socket_path("router", 42)
    assert p == Path("/elsewhere/claude-cpm-router-42.sock")


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        "Router",
        "router-1",
        "1router",
        "router/x",
        "router.x",
        "ROUTER",
        "router x",
    ],
)
def test_socket_path_rejects_invalid_plugin_names(bad_name: str) -> None:
    """Plugin name must match ^[a-z][a-z0-9_]*$."""
    with pytest.raises(ValueError, match="plugin"):
        socket_path(bad_name, 1)


@pytest.mark.parametrize(
    "good_name",
    ["router", "proj", "todoist", "trello", "jira", "wiki_log", "a", "a1", "a_b_c"],
)
def test_socket_path_accepts_valid_plugin_names(good_name: str) -> None:
    """Valid plugin names: leading lowercase letter, then [a-z0-9_]*."""
    p = socket_path(good_name, 7)
    assert p.name == f"claude-cpm-{good_name}-7.sock"


# ── socket_glob tests ───────────────────────────────────────────────────────


def test_socket_glob_filename_only() -> None:
    """socket_glob returns a filename glob, not a full path."""
    assert socket_glob("todoist") == "claude-cpm-todoist-*.sock"


def test_socket_glob_validates_plugin_name() -> None:
    """socket_glob applies the same plugin-name validation as socket_path."""
    with pytest.raises(ValueError, match="plugin"):
        socket_glob("Bad-Name")


# ── legacy_socket_path tests ─────────────────────────────────────────────────


def test_legacy_socket_path_format() -> None:
    """legacy_socket_path returns <socket_dir>/claude-cpm-<plugin>.sock (no PID)."""
    p = legacy_socket_path("trello")
    assert p == socket_dir() / "claude-cpm-trello.sock"


def test_legacy_socket_path_uses_current_socket_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    """legacy_socket_path uses the current socket_dir() at call time."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: "/elsewhere")
    p = legacy_socket_path("router")
    assert p == Path("/elsewhere/claude-cpm-router.sock")


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        "Router",
        "router-1",
        "1router",
        "router/x",
        "router.x",
        "ROUTER",
        "router x",
    ],
)
def test_legacy_socket_path_rejects_invalid_plugin_names(bad_name: str) -> None:
    """legacy_socket_path applies the same plugin-name validation as socket_path."""
    with pytest.raises(ValueError, match="plugin"):
        legacy_socket_path(bad_name)


@pytest.mark.parametrize(
    "good_name",
    ["router", "proj", "todoist", "trello", "jira", "wiki_log", "a", "a1", "a_b_c"],
)
def test_legacy_socket_path_accepts_valid_plugin_names(good_name: str) -> None:
    """Valid plugin names: leading lowercase letter, then [a-z0-9_]*."""
    p = legacy_socket_path(good_name)
    assert p.name == f"claude-cpm-{good_name}.sock"


def test_legacy_socket_path_consistent_with_socket_path_prefix() -> None:
    """legacy_socket_path shares the claude-cpm- prefix + socket_dir w/ socket_path."""
    plugin = "trello"
    legacy = legacy_socket_path(plugin)
    pid_tagged = socket_path(plugin, 1234)
    assert legacy.parent == pid_tagged.parent
    assert legacy.name.startswith("claude-cpm-")
    assert pid_tagged.name.startswith("claude-cpm-")
    # Legacy form is the no-PID variant: claude-cpm-trello.sock
    # PID-tagged form: claude-cpm-trello-1234.sock
    assert legacy.name == f"claude-cpm-{plugin}.sock"
    assert pid_tagged.name == f"claude-cpm-{plugin}-1234.sock"


# ── round-trip integration test ─────────────────────────────────────────────


def test_round_trip_bind_then_glob_match(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind a real socket via socket_path, then resolve it back via socket_dir + socket_glob."""
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))
    bind_path = socket_path("test_plugin", 99999)
    sock = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
    try:
        sock.bind(str(bind_path))
        matches = list(socket_dir().glob(socket_glob("test_plugin")))
        assert bind_path in matches
    finally:
        sock.close()
        if bind_path.exists():
            bind_path.unlink()
