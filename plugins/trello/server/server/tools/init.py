"""Trello init tool — validate credentials and write config."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import yaml
from mcp.server.fastmcp import FastMCP

import server.lib.client as client_mod
import server.lib.config as config_mod


def register(app: FastMCP) -> None:
    @app.tool(description="Initialize Trello configuration: validate credentials and save config.")
    def trello_init(
        api_key: str,
        token: str,
        default_board_id: str = "",
        allowed_board_ids: list[str] | None = None,
        rate_limit_per_10s: int = 100,
    ) -> str:
        if allowed_board_ids is None:
            allowed_board_ids = []

        # Validate credentials against the Trello API
        resp = httpx.get(
            "https://api.trello.com/1/members/me",
            params={"key": api_key, "token": token},
            timeout=30,
        )
        if not resp.is_success:
            return json.dumps({"error": f"Credential validation failed: {resp.status_code} {resp.text}"})

        member = resp.json()

        # Build YAML config
        config_data = {
            "api_key": api_key,
            "token": token,
            "default_board_id": default_board_id,
            "rate_limit_per_10s": rate_limit_per_10s,
            "allowed_board_ids": allowed_board_ids,
        }

        config_path = Path("~/.claude/trello.yaml").expanduser()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w") as f:
            yaml.dump(config_data, f, default_flow_style=False)

        # Clear cached config and client so next call picks up the new config
        config_mod._cached_config = None
        client_mod._cached_client = None

        return json.dumps({
            "ok": True,
            "username": member.get("username", ""),
            "config_path": str(config_path),
        })
