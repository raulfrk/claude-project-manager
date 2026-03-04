"""MCP tools for managing base repository registry."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import storage
from server.lib.git import is_git_repo
from server.lib.models import BaseRepo

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def add_repo(label: str, path: str, default_branch: str = "main") -> str:
    """Register a new base repository."""
    abs_path = str(Path(path).expanduser().resolve())
    if not Path(abs_path).exists():
        return f"Error: path does not exist: {abs_path}"
    if not is_git_repo(abs_path):
        return f"Error: not a git repository: {abs_path}"

    config = storage.load()
    if any(r.label == label for r in config.base_repos):
        return (
            f"A repo with label '{label}' already exists. Use a different label or remove it first."
        )

    config.base_repos.append(BaseRepo(label=label, path=abs_path, default_branch=default_branch))
    storage.save(config)
    return f"Registered repo '{label}' at {abs_path} (default branch: {default_branch})."


def remove_repo(label: str) -> str:
    """Unregister a base repository by label."""
    config = storage.load()
    before = len(config.base_repos)
    config.base_repos = [r for r in config.base_repos if r.label != label]
    if len(config.base_repos) == before:
        return f"No repo with label '{label}' found."
    storage.save(config)
    return f"Removed repo '{label}'."


def list_repos() -> str:
    """List all configured base repositories."""
    config = storage.load()
    if not config.base_repos:
        return "No base repos configured. Use /worktree:add-repo to register one."
    lines = [f"Base repos (config: {storage.config_path()}):"]
    for r in config.base_repos:
        lines.append(f"  [{r.label}] {r.path} (default: {r.default_branch})")
    return "\n".join(lines)


def get_repo(label: str) -> BaseRepo | None:
    """Return a base repo by label, or None."""
    config = storage.load()
    return next((r for r in config.base_repos if r.label == label), None)


def register(app: FastMCP) -> None:
    """Register repo tools with the MCP application."""

    @app.tool(description="Register a new base git repository for worktree creation.")
    def wt_add_repo(label: str, path: str, default_branch: str = "main") -> str:
        return add_repo(label, path, default_branch)

    @app.tool(description="Unregister a base repository by its label.")
    def wt_remove_repo(label: str) -> str:
        return remove_repo(label)

    @app.tool(description="List all configured base repositories.")
    def wt_list_repos() -> str:
        return list_repos()
