"""Zoxide frecency database helpers."""

from __future__ import annotations

import subprocess


def zoxide_boost(path: str, times: int = 10) -> None:
    """Run ``zoxide add`` *times* times to boost *path* in the frecency DB."""
    try:
        for _ in range(times):
            subprocess.run(["zoxide", "add", path], check=False, capture_output=True)
    except FileNotFoundError:
        pass  # zoxide not installed


def zoxide_remove(path: str) -> None:
    """Run ``zoxide remove`` once for *path*."""
    try:
        subprocess.run(["zoxide", "remove", path], check=False, capture_output=True)
    except FileNotFoundError:
        pass  # zoxide not installed
