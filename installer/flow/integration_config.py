# installer/flow/integration_config.py
"""prompt_toolkit replacement for Textual integration config screens.

Each service (Todoist, Trello, Jira) gets a configure_<service>(console)
function. All share _run_integration_form which handles:
 - submit
 - sync-disabled skip validation
 - synchronous httpx credential validation inside console.status()
 - re-prompt with pre-filled values + error banner on validation failure
 - cancel returns None

Existing yaml values pre-fill FieldSpec defaults so users never re-type
unchanged credentials.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import httpx
from rich.console import Console

from installer._config_loader import ConfigLoadError, load_existing_yaml
from installer.flow.form import FieldSpec, run_form


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return load_existing_yaml(path) or {}
    except ConfigLoadError:
        return {}


def _run_integration_form(
    service_name: str,
    fields: list[FieldSpec],
    validator: Callable[[dict[str, Any]], str | None],
    console: Console,
) -> dict[str, Any] | None:
    """Shared form runner: submit → skip-if-disabled → validate → re-prompt on err."""
    error: str | None = None
    current_fields = fields
    while True:
        result = run_form(
            current_fields,
            console,
            title=f"{service_name} Configuration",
            error_message=error,
        )
        if result is None:
            return None
        # B2: skip validation when sync disabled
        if not result.get("sync_enabled", True):
            return result
        with console.status(f"Validating {service_name} credentials..."):
            error = validator(result)
        if error is None:
            return result
        # Re-build fields with current submitted values as defaults
        current_fields = [
            FieldSpec(
                key=f.key,
                label=f.label,
                kind=f.kind,
                default=result.get(f.key, f.default),
                choices=f.choices,
                validator=f.validator,
                help_text=f.help_text,
                group=f.group,
            )
            for f in current_fields
        ]


def _todoist_validator(values: dict[str, Any]) -> str | None:
    token = (values.get("api_token") or "").strip()
    if not token:
        return "API token is required"
    try:
        resp = httpx.get(
            "https://api.todoist.com/api/v1/projects",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        if resp.status_code == 401:
            return "Invalid API token"
        if resp.status_code != 200:
            return f"Todoist API error: {resp.status_code}"
    except httpx.ConnectError:
        return "Cannot reach Todoist API — check network"
    except httpx.TimeoutException:
        return "Todoist API timeout"
    return None


def configure_todoist(console: Console) -> dict[str, Any] | None:
    """Todoist integration config form. Returns dict or None on cancel."""
    claude_home = Path.home() / ".claude"
    todoist_cfg = _load_yaml(claude_home / "todoist.yaml")
    proj_cfg = _load_yaml(claude_home / "proj.yaml")
    sync_section = (proj_cfg.get("sync", {}) or {}).get("todoist", {}) or {}

    fields = [
        FieldSpec(
            key="api_token",
            label="API Token",
            kind="password",
            default=(
                todoist_cfg.get("api_token") or sync_section.get("api_token") or ""
            ),
            help_text="Get from Settings > Integrations > API token in Todoist",
        ),
        FieldSpec(
            key="sync_enabled",
            label="Enable Todoist sync",
            kind="bool",
            default=bool(sync_section.get("enabled", False)),
        ),
        FieldSpec(
            key="auto_sync",
            label="Auto-sync on todo changes",
            kind="bool",
            default=bool(sync_section.get("auto_sync", True)),
        ),
        FieldSpec(
            key="root_only",
            label="Sync root-level todos only",
            kind="bool",
            default=bool(sync_section.get("root_only", False)),
        ),
    ]
    return _run_integration_form("Todoist", fields, _todoist_validator, console)
