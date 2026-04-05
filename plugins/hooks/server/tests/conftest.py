"""Shared fixtures for hooks plugin tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from server.lib.models import Hook, HookRegistry


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


# ── YAML file fixtures ───────────────────────────────────────────────────────


@pytest.fixture()
def hooks_yaml(tmp_path: Path) -> Path:
    """Return path to a temporary hooks.yaml file (does not exist yet)."""
    return tmp_path / "hooks.yaml"


@pytest.fixture()
def failures_yaml(tmp_path: Path) -> Path:
    """Return path to a temporary hooks-failures.yaml file (does not exist yet)."""
    return tmp_path / "hooks-failures.yaml"


@pytest.fixture()
def verifications_yaml(tmp_path: Path) -> Path:
    """Return path to a temporary hooks-verifications.yaml file (does not exist yet)."""
    return tmp_path / "hooks-verifications.yaml"


@pytest.fixture()
def proj_yaml(tmp_path: Path) -> Path:
    """Return path to a temporary proj.yaml file (does not exist yet)."""
    return tmp_path / "proj.yaml"


# ── Helper to write YAML ─────────────────────────────────────────────────────


@pytest.fixture()
def write_yaml(tmp_path: Path):  # noqa: ARG001
    """Return a helper that writes arbitrary data to a YAML path."""

    def _write(path: Path, data: Any) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump(data, default_flow_style=False, sort_keys=False))
        return path

    return _write


# ── Model fixtures ───────────────────────────────────────────────────────────


@pytest.fixture()
def sample_hook() -> Hook:
    """A single sample Hook instance."""
    return Hook(
        id="hook-001",
        trigger_tool="proj_init",
        target_tool="perms_setup",
        server="perms",
        param_mapping={"path": "${result.path}"},
        blocking=False,
        condition=None,
    )


@pytest.fixture()
def sample_hook_blocking() -> Hook:
    """A blocking hook with a condition."""
    return Hook(
        id="hook-002",
        trigger_tool="proj_init",
        target_tool="todoist_sync",
        server="todoist",
        param_mapping={"project": "${result.title}"},
        blocking=True,
        condition="sync.todoist.enabled",
    )


@pytest.fixture()
def sample_registry(sample_hook: Hook, sample_hook_blocking: Hook) -> HookRegistry:
    """A HookRegistry with two hooks pre-loaded."""
    return HookRegistry(
        hooks=[sample_hook, sample_hook_blocking],
        servers={"perms": {}, "todoist": {"url": "http://localhost:9100"}},
        settings={"max_depth": 3},
    )


@pytest.fixture()
def empty_registry() -> HookRegistry:
    """An empty HookRegistry."""
    return HookRegistry()


@pytest.fixture()
def populated_hooks_yaml(
    hooks_yaml: Path,
    sample_registry: HookRegistry,
    write_yaml,
) -> Path:
    """Write sample_registry to hooks.yaml and return the path."""
    write_yaml(hooks_yaml, sample_registry.to_dict())
    return hooks_yaml
