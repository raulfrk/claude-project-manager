"""Todoist init tool — validate credentials and write config."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

import httpx
import yaml

import server.lib.client as client_mod
import server.lib.config as config_mod

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def _mask_token(token: str) -> str:
    """Return masked token for safe display in error messages."""
    if len(token) <= 4:
        return "***"
    return f"***{token[-4:]}"


def register(app: FastMCP) -> None:
    @app.tool(description="Initialize Todoist configuration: validate API token and save config.")
    def todoist_init(
        api_token: str,
        enabled: bool = True,
        auto_sync: bool = True,
        root_only: bool = False,
    ) -> str:
        # Validate credentials against the Todoist API
        resp = httpx.get(
            "https://api.todoist.com/api/v1/projects",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=30,
        )
        if not resp.is_success:
            return json.dumps(
                {
                    "error": f"Credential validation failed: {resp.status_code} {resp.text}",
                    "token": _mask_token(api_token),
                }
            )

        # Parse the response safely
        try:
            data = resp.json()
            if not isinstance(data, dict):
                raise ValueError("unexpected response type")
            project_count = len(data.get("results", []))
        except (json.JSONDecodeError, ValueError):
            return json.dumps(
                {
                    "error": "todoist_init succeeded but response was not valid JSON",
                    "status_code": resp.status_code,
                }
            )

        # Build YAML config
        config_data = {
            "api_token": api_token,
            "enabled": enabled,
            "auto_sync": auto_sync,
            "root_only": root_only,
        }

        config_path = Path("~/.claude/todoist.yaml").expanduser()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w") as f:
            yaml.dump(config_data, f, default_flow_style=False)

        # Clear cached config and client so next call picks up the new config
        config_mod._cached_config = None
        client_mod._cached_client = None

        return json.dumps(
            {
                "ok": True,
                "project_count": project_count,
                "config_path": str(config_path),
            }
        )
