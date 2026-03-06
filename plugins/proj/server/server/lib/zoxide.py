"""Zoxide integration helpers — boost and remove paths from zoxide's frecency database."""

from __future__ import annotations

import subprocess

from server.lib.models import ProjConfig, ProjectMeta


def resolve_enabled(cfg: ProjConfig, meta: ProjectMeta) -> bool:
    """Return the effective zoxide_integration flag.

    Per-project value wins if non-None, otherwise falls back to global config.
    """
    if meta.zoxide_integration is not None:
        return meta.zoxide_integration
    return cfg.zoxide_integration


def zoxide_boost(path: str, times: int = 10) -> None:
    """Run ``zoxide add <path>`` *times* times to boost its frecency ranking.

    Silently skips if zoxide is not installed (FileNotFoundError).
    """
    for _ in range(times):
        try:
            subprocess.run(["zoxide", "add", path], check=False)  # noqa: S603, S607
        except FileNotFoundError:
            return  # zoxide not installed — skip silently


def zoxide_remove(path: str) -> None:
    """Run ``zoxide remove <path>`` once.

    Silently skips if zoxide is not installed (FileNotFoundError).
    """
    try:
        subprocess.run(["zoxide", "remove", path], check=False)  # noqa: S603, S607
    except FileNotFoundError:
        pass  # zoxide not installed — skip silently
