"""Jira configuration loading."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class JiraConfig:
    """Jira Server API configuration."""

    personal_access_token: str
    base_url: str
    allowed_project_keys: list[str] = field(default_factory=list)
    default_user: str = ""
    rate_limit_per_10s: int = 100


_cached_config: JiraConfig | None = None


def load_config() -> JiraConfig:
    """Load Jira configuration from YAML file or environment variables.

    Resolution order:
    1. JIRA_CONFIG env var points to a YAML file -> parse it
    2. Default ~/.claude/jira.yaml if it exists -> parse it
    3. JIRA_PAT and JIRA_BASE_URL env vars
    4. Raise an error with setup instructions
    """
    global _cached_config
    if _cached_config is not None:
        return _cached_config

    config_path = Path(os.environ.get("JIRA_CONFIG", "~/.claude/jira.yaml")).expanduser()

    if config_path.exists():
        with config_path.open() as f:
            try:
                data = yaml.safe_load(f) or {}
            except yaml.YAMLError as exc:
                raise ValueError(f"Invalid YAML in {config_path}: {exc}") from exc
        _cached_config = JiraConfig(
            personal_access_token=data.get("personal_access_token", ""),
            base_url=data.get("base_url", ""),
            allowed_project_keys=data.get("allowed_project_keys", []),
            default_user=data.get("default_user", ""),
            rate_limit_per_10s=data.get("rate_limit_per_10s", 100),
        )
        if not _cached_config.personal_access_token or not _cached_config.base_url:
            msg = f"Jira YAML config at {config_path} is missing personal_access_token or base_url."
            raise ValueError(msg)
        return _cached_config

    pat = os.environ.get("JIRA_PAT", "")
    base_url = os.environ.get("JIRA_BASE_URL", "")
    if pat and base_url:
        _cached_config = JiraConfig(personal_access_token=pat, base_url=base_url)
        return _cached_config

    msg = (
        "Jira config not found. Create ~/.claude/jira.yaml or set JIRA_PAT/JIRA_BASE_URL env vars."
    )
    raise ValueError(msg)
