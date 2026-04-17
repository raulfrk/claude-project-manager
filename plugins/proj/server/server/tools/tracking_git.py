"""MCP tool for git tracking flush."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from server.lib import storage
from server.lib import tracking_git as tg
from server.tools.config import require_project

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(app: FastMCP) -> None:
    """Register tracking_git_flush tool with the MCP app."""

    @app.tool(
        description=(
            "Commit tracking directory changes to git and optionally push to GitHub. "
            "Call at the end of skill invocations for batched commits."
        )
    )
    async def tracking_git_flush(
        commit_message: str | None = None,
        project_name: str | None = None,
    ) -> str:
        result = require_project(project_name)
        if isinstance(result, str):
            return result
        cfg, name = result

        meta = storage.load_meta(cfg, name)
        enabled, github_enabled, github_repo_format = tg.resolve_config(cfg, meta)

        if not enabled:
            return json.dumps({"status": "disabled"})

        tracking_path = Path(cfg.tracking_dir).expanduser()
        proj_dir = tracking_path / name
        if not tg.ensure_git_repo(tracking_path):
            return json.dumps({"status": "error", "message": "Failed to init git repo"})

        try:
            # Pass enabled=True explicitly since we already verified enabled above,
            # which may differ from cfg.git_tracking.enabled (per-project override).
            tg.write_json_exports(cfg, name, force=True)
        except Exception as e:
            logger.warning("write_json_exports failed, committing whatever is on disk: %s", e)

        msg = commit_message or f"[{name}] Update {name}"
        sha = await tg.tracking_commit_async(proj_dir, msg)
        if not sha:
            return json.dumps({"status": "no_changes"})

        pushed = False
        if github_enabled:
            repo_name = tg.resolve_repo_name(github_repo_format, name)
            tg.ensure_github_repo(repo_name)
            tg.ensure_remote(tracking_path, repo_name)
            pushed = await tg.tracking_push_async(tracking_path)

        return json.dumps({"status": "ok", "sha": sha, "pushed": pushed, "message": msg})
