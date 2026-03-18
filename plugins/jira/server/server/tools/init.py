"""Jira init tool — validate credentials and write config."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import yaml
from mcp.server.fastmcp import FastMCP

import server.lib.client as client_mod
import server.lib.config as config_mod


def register(app: FastMCP) -> None:
    @app.tool(description="Initialize Jira configuration: validate credentials and save config.")
    def jira_init(
        personal_access_token: str,
        base_url: str,
        allowed_project_keys: list[str] | None = None,
        default_user: str = "",
        rate_limit_per_10s: int = 100,
    ) -> str:
        if allowed_project_keys is None:
            allowed_project_keys = []

        # Normalize base_url
        base_url = base_url.rstrip("/")

        # Validate credentials against the Jira REST API
        resp = httpx.get(
            f"{base_url}/rest/api/2/myself",
            headers={"Authorization": f"Bearer {personal_access_token}"},
            timeout=30,
        )
        if not resp.is_success:
            return json.dumps(
                {"error": f"Credential validation failed: {resp.status_code} {resp.text}"}
            )

        myself = resp.json()

        # Build YAML config
        config_data = {
            "personal_access_token": personal_access_token,
            "base_url": base_url,
            "allowed_project_keys": allowed_project_keys,
            "default_user": default_user,
            "rate_limit_per_10s": rate_limit_per_10s,
        }

        config_path = Path("~/.claude/jira.yaml").expanduser()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w") as f:
            yaml.dump(config_data, f, default_flow_style=False)

        # Clear cached config and client so next call picks up the new config
        config_mod._cached_config = None
        client_mod._cached_client = None

        return json.dumps({
            "ok": True,
            "displayName": myself.get("displayName", ""),
            "emailAddress": myself.get("emailAddress", ""),
            "config_path": str(config_path),
        })
