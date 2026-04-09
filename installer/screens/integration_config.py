"""Integration configuration screens (Todoist, Trello, Jira)."""

from __future__ import annotations

import contextlib
import os
import tempfile
from abc import abstractmethod
from pathlib import Path
from typing import Any

import yaml
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Input,
    Label,
    LoadingIndicator,
    Static,
    Switch,
)


def _atomic_write(path: Path, content: str) -> None:
    """Write content to a file atomically via tmp + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        Path(tmp_path).replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            Path(tmp_path).unlink()
        raise


class BaseIntegrationScreen(Screen[dict[str, str | bool] | None]):
    """Base class for integration config screens (Todoist, Trello, Jira).

    Subclasses must define ``service_name``, ``config_path``,
    ``compose_fields()``, ``_validate_credentials()``, and
    ``_collect_values()``.
    """

    CSS = """
    BaseIntegrationScreen {
        align: center middle;
    }

    #integration-form {
        width: 72;
        max-height: 85%;
        padding: 1 2;
        border: round $accent;
        background: $surface;
    }

    #integration-scroll {
        height: 1fr;
        max-height: 100%;
        min-height: 3;
    }

    #integration-title {
        text-align: center;
        text-style: bold;
        color: $text;
        background: $accent;
        padding: 1 0;
        margin: 0 0 1 0;
    }

    .field-group {
        height: auto;
        margin: 1 0 0 0;
    }

    .field-label {
        height: 1;
        padding: 0 1;
        color: $accent;
        text-style: bold;
    }

    .field-hint {
        height: 1;
        padding: 0 1;
        color: $text-muted;
        text-style: italic;
    }

    Input {
        margin: 0 1;
        border: tall $primary-background;
    }

    Input:focus {
        border: tall $accent;
    }

    .switch-row {
        height: 3;
        padding: 0 1;
        margin: 0 0 0 0;
    }

    .switch-row Label {
        padding: 1 1;
        width: 1fr;
        color: $text;
    }

    .switch-row Switch {
        width: auto;
    }

    #validation-error {
        height: auto;
        padding: 0 1;
        color: $error;
        text-style: bold;
        display: none;
    }

    #validation-error.visible {
        display: block;
    }

    #validation-loading {
        height: 3;
        display: none;
    }

    #validation-loading.visible {
        display: block;
    }

    #button-bar {
        height: auto;
        min-height: 3;
        align: center middle;
        margin: 1 0 0 0;
        border-top: solid $primary-background;
        padding: 1 2;
    }

    #button-bar Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        ("escape", "skip", "Skip"),
    ]

    # -- Abstract / overridable properties and methods --

    @property
    @abstractmethod
    def service_name(self) -> str:
        """Human-readable service name, e.g. 'Todoist'."""

    @property
    @abstractmethod
    def config_path(self) -> Path:
        """Path to the YAML config file for this integration."""

    @abstractmethod
    def compose_fields(self) -> ComposeResult:
        """Yield the service-specific input fields."""

    @abstractmethod
    async def _validate_credentials(self) -> str | None:
        """Validate the entered credentials.

        Returns None on success, or an error string on failure.
        """

    @abstractmethod
    def _collect_values(self) -> dict[str, str | bool]:
        """Gather values from the form fields."""

    # -- Common methods --

    def _read_existing_config(self) -> dict[str, Any]:
        """Read YAML from config_path, return {} if not found or invalid."""
        try:
            text = self.config_path.read_text(encoding="utf-8")
            data = yaml.safe_load(text)
            return data if isinstance(data, dict) else {}
        except (FileNotFoundError, OSError, yaml.YAMLError):
            return {}

    def _write_config(self, values: dict[str, Any]) -> None:
        """Write values to config_path as YAML using atomic write."""
        content = yaml.dump(values, default_flow_style=False, sort_keys=False)
        _atomic_write(self.config_path, content)

    # -- Compose --

    def compose(self) -> ComposeResult:
        with Vertical(id="integration-form"):
            yield Static(
                f"Configure {self.service_name}",
                id="integration-title",
            )

            with VerticalScroll(id="integration-scroll"):
                # Sync enabled toggle
                with Horizontal(classes="switch-row"):
                    yield Label("Sync enabled")
                    existing = self._read_existing_config()
                    default_enabled = bool(existing.get("enabled", False))
                    yield Switch(value=default_enabled, id="sync_enabled")

                # Auto-sync toggle
                with Horizontal(classes="switch-row"):
                    yield Label("Auto sync")
                    default_auto_sync = bool(existing.get("auto_sync", True))
                    yield Switch(value=default_auto_sync, id="auto_sync")

                # Service-specific fields from subclass
                yield from self.compose_fields()

            # Validation error (hidden by default)
            yield Label("", id="validation-error")

            # Loading indicator (hidden by default)
            yield LoadingIndicator(id="validation-loading")

            # Buttons (always visible outside scroll)
            with Horizontal(id="button-bar"):
                yield Button(
                    "Continue",
                    variant="primary",
                    id="btn-continue",
                )
                yield Button("Skip", variant="default", id="btn-skip")
        yield Footer()

    def on_mount(self) -> None:
        """Auto-focus the Continue button."""
        btn = self.query_one("#btn-continue", Button)
        self.set_focus(btn)

    # -- Actions & events --

    def action_skip(self) -> None:
        """Skip this integration screen."""
        self.dismiss(None)

    def _show_error(self, message: str) -> None:
        """Display an inline validation error."""
        error_label = self.query_one("#validation-error", Label)
        error_label.update(message)
        error_label.add_class("visible")

    def _hide_error(self) -> None:
        """Hide the inline validation error."""
        error_label = self.query_one("#validation-error", Label)
        error_label.remove_class("visible")

    def _show_loading(self) -> None:
        """Show the loading indicator."""
        self.query_one("#validation-loading").add_class("visible")

    def _hide_loading(self) -> None:
        """Hide the loading indicator."""
        self.query_one("#validation-loading").remove_class("visible")

    async def _on_continue(self) -> None:
        """Handle Continue: validate, then dismiss with values."""
        self._hide_error()
        self._show_loading()

        try:
            error = await self._validate_credentials()
        finally:
            self._hide_loading()

        if error:
            self._show_error(error)
            return

        values = self._collect_values()
        self.dismiss(values)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle Continue and Skip button presses."""
        if event.button.id == "btn-continue":
            self.run_worker(self._on_continue(), exclusive=True)
        elif event.button.id == "btn-skip":
            self.dismiss(None)


class TodoistConfigScreen(BaseIntegrationScreen):
    """Configuration screen for Todoist integration."""

    @property
    def service_name(self) -> str:
        return "Todoist"

    @property
    def config_path(self) -> Path:
        return Path.home() / ".claude" / "todoist.yaml"

    def compose_fields(self) -> ComposeResult:
        existing = self._read_existing_config()
        with Vertical(classes="field-group"):
            yield Label("API Token", classes="field-label")
            yield Label(
                "Get from Settings > Integrations > API token in Todoist",
                classes="field-hint",
            )
            yield Input(
                id="api_token",
                password=True,
                value=str(existing.get("api_token", "")),
            )

    async def _validate_credentials(self) -> str | None:
        token = self.query_one("#api_token", Input).value.strip()
        if not token:
            return "API token is required"
        # Test the token against Todoist REST API
        import httpx

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

    def _collect_values(self) -> dict[str, str | bool]:
        return {
            "api_token": self.query_one("#api_token", Input).value.strip(),
            "enabled": self.query_one("#sync_enabled", Switch).value,
            "auto_sync": self.query_one("#auto_sync", Switch).value,
        }


class TrelloConfigScreen(BaseIntegrationScreen):
    """Configuration screen for the Trello integration."""

    @property
    def service_name(self) -> str:
        return "Trello"

    @property
    def config_path(self) -> Path:
        return Path.home() / ".claude" / "trello.yaml"

    def compose_fields(self) -> ComposeResult:
        existing = self._read_existing_config()
        # API Key (masked)
        with Vertical(classes="field-group"):
            yield Label("API Key", classes="field-label")
            yield Label(
                "Get from https://trello.com/power-ups/admin/",
                classes="field-hint",
            )
            yield Input(
                id="api_key",
                password=True,
                value=existing.get("api_key", ""),
            )
        # Token (masked)
        with Vertical(classes="field-group"):
            yield Label("Token", classes="field-label")
            yield Input(
                id="token",
                password=True,
                value=existing.get("token", ""),
            )
        # Default Board ID (plain text)
        with Vertical(classes="field-group"):
            yield Label("Default Board ID", classes="field-label")
            yield Label(
                "The board ID from your Trello board URL",
                classes="field-hint",
            )
            yield Input(
                id="default_board_id",
                value=existing.get("default_board_id", ""),
            )

    async def _validate_credentials(self) -> str | None:
        key = self.query_one("#api_key", Input).value.strip()
        token = self.query_one("#token", Input).value.strip()
        if not key or not token:
            return "API key and token are both required"
        import httpx

        try:
            resp = httpx.get(
                f"https://api.trello.com/1/members/me?key={key}&token={token}",
                timeout=10,
            )
            if resp.status_code == 401:
                return "Invalid API key or token"
            if resp.status_code != 200:
                return f"Trello API error: {resp.status_code}"
        except httpx.ConnectError:
            return "Cannot reach Trello API — check network"
        except httpx.TimeoutException:
            return "Trello API timeout"
        return None

    def _collect_values(self) -> dict[str, str | bool]:
        return {
            "api_key": self.query_one("#api_key", Input).value.strip(),
            "token": self.query_one("#token", Input).value.strip(),
            "default_board_id": self.query_one(
                "#default_board_id", Input
            ).value.strip(),
            "enabled": self.query_one("#sync_enabled", Switch).value,
            "auto_sync": self.query_one("#auto_sync", Switch).value,
        }


class JiraConfigScreen(BaseIntegrationScreen):
    """Configuration screen for the Jira integration."""

    @property
    def service_name(self) -> str:
        return "Jira"

    @property
    def config_path(self) -> Path:
        return Path.home() / ".claude" / "jira.yaml"

    def compose_fields(self) -> ComposeResult:
        existing = self._read_existing_config()
        with Vertical(classes="field-group"):
            yield Label("Base URL", classes="field-label")
            yield Label("e.g., https://yourcompany.atlassian.net", classes="field-hint")
            yield Input(id="base_url", value=str(existing.get("base_url", "")))
        with Vertical(classes="field-group"):
            yield Label("Username / Email", classes="field-label")
            yield Input(id="default_user", value=str(existing.get("default_user", "")))
        with Vertical(classes="field-group"):
            yield Label("Personal Access Token", classes="field-label")
            yield Input(
                id="personal_access_token",
                password=True,
                value=str(existing.get("personal_access_token", "")),
            )
        with Vertical(classes="field-group"):
            yield Label("Default Project Key", classes="field-label")
            yield Label("e.g., PROJ, TEAM", classes="field-hint")
            yield Input(
                id="default_project", value=str(existing.get("default_project", ""))
            )

    async def _validate_credentials(self) -> str | None:
        base_url = self.query_one("#base_url", Input).value.strip().rstrip("/")
        token = self.query_one("#personal_access_token", Input).value.strip()
        if not base_url:
            return "Base URL is required"
        if not token:
            return "Personal access token is required"
        import httpx

        try:
            resp = httpx.get(
                f"{base_url}/rest/api/3/myself",
                headers={"Authorization": f"Bearer {token}"},
                timeout=10,
            )
            if resp.status_code == 401:
                return "Invalid personal access token"
            if resp.status_code != 200:
                return f"Jira API error: {resp.status_code}"
        except httpx.ConnectError:
            return f"Cannot reach {base_url} — check URL and network"
        except httpx.TimeoutException:
            return "Jira API timeout"
        return None

    def _collect_values(self) -> dict[str, str | bool]:
        return {
            "base_url": self.query_one("#base_url", Input).value.strip().rstrip("/"),
            "default_user": self.query_one("#default_user", Input).value.strip(),
            "personal_access_token": self.query_one(
                "#personal_access_token", Input
            ).value.strip(),
            "default_project": self.query_one("#default_project", Input).value.strip(),
            "enabled": self.query_one("#sync_enabled", Switch).value,
            "auto_sync": self.query_one("#auto_sync", Switch).value,
        }
