"""confluence_init tool — write ~/.claude/confluence.yaml."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from server.lib.client import reset_client
from server.lib.config import DEFAULT_CONFIG_PATH

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def confluence_init(
        deployment: str,
        base_url: str,
        email: str | None = None,
        api_token: str | None = None,
        personal_access_token: str | None = None,
        allowed_spaces: list[str] | None = None,
    ) -> dict[str, Any]:
        """Initialize or overwrite ~/.claude/confluence.yaml."""
        cfg_path = Path(os.environ.get("CONFLUENCE_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()
        cfg_path.parent.mkdir(parents=True, exist_ok=True)

        data: dict[str, Any] = {
            "deployment": deployment,
            "base_url": base_url.rstrip("/"),
            "allowed_spaces": allowed_spaces or [],
        }
        if email:
            data["email"] = email
        if api_token:
            data["api_token"] = api_token
        if personal_access_token:
            data["personal_access_token"] = personal_access_token

        cfg_path.write_text(yaml.safe_dump(data, sort_keys=True))
        reset_client()

        return {"status": "ok", "config_path": str(cfg_path)}
