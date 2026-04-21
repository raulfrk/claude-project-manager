"""Confluence plugin config loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from server.lib.errors import ConfigError

DEFAULT_CONFIG_PATH = "~/.claude/confluence.yaml"


@dataclass(frozen=True)
class ConfluenceConfig:
    deployment: str  # "auto" | "cloud" | "server"
    base_url: str
    email: str | None = None
    api_token: str | None = None
    personal_access_token: str | None = None
    allowed_spaces: list[str] = field(default_factory=list)
    rate_limit_per_10s: int = 10
    default_max_results: int = 25
    max_results_cap: int = 100
    timeout_seconds: int = 30


def load_config(path: str | None = None) -> ConfluenceConfig:
    """Load config from YAML, applying env var overrides."""
    effective_path = path or os.environ.get("CONFLUENCE_CONFIG", DEFAULT_CONFIG_PATH)
    expanded = Path(effective_path).expanduser()
    if not expanded.exists():
        raise ConfigError(f"Confluence config not found: {expanded}")

    with expanded.open() as f:
        raw = yaml.safe_load(f) or {}

    base_url = (os.environ.get("CONFLUENCE_BASE_URL") or raw.get("base_url", "")).rstrip("/")

    return ConfluenceConfig(
        deployment=raw.get("deployment", "auto"),
        base_url=base_url,
        email=os.environ.get("CONFLUENCE_EMAIL") or raw.get("email"),
        api_token=os.environ.get("CONFLUENCE_API_TOKEN") or raw.get("api_token"),
        personal_access_token=(
            os.environ.get("CONFLUENCE_PAT") or raw.get("personal_access_token")
        ),
        allowed_spaces=list(raw.get("allowed_spaces") or []),
        rate_limit_per_10s=int(raw.get("rate_limit_per_10s", 10)),
        default_max_results=int(raw.get("default_max_results", 25)),
        max_results_cap=int(raw.get("max_results_cap", 100)),
        timeout_seconds=int(raw.get("timeout_seconds", 30)),
    )
