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


def list_worktree_paths(base_repo: str) -> list[str]:
    """Return worktree paths for a git repo, excluding the base repo itself.

    Runs ``git worktree list --porcelain`` and parses lines starting with
    ``worktree ``.  Returns an empty list if git is not installed, the
    directory does not exist, or the directory is not a git repository.
    """
    try:
        result = subprocess.run(  # noqa: S603, S607
            ["git", "worktree", "list", "--porcelain"],
            cwd=base_repo,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            return []
        paths: list[str] = []
        for line in result.stdout.splitlines():
            if line.startswith("worktree "):
                wt_path = line[len("worktree ") :]
                if wt_path != base_repo:
                    paths.append(wt_path)
        return paths
    except (FileNotFoundError, OSError):
        return []
