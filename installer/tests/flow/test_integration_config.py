# installer/tests/flow/test_integration_config.py
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from rich.console import Console

from installer.flow.integration_config import (
    configure_jira,
    configure_todoist,
    configure_trello,
)


class TestConfigureTodoist:
    def test_cancel_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        with patch("installer.flow.integration_config.run_form", return_value=None):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = configure_todoist(console)
        assert result is None

    def test_defaults_from_existing_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Existing creds in todoist.yaml MUST pre-fill api_token."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "todoist.yaml").write_text(
            yaml.safe_dump({"api_token": "existing-token"})
        )
        (fake_home / ".claude" / "proj.yaml").write_text(
            yaml.safe_dump(
                {
                    "sync": {
                        "todoist": {
                            "enabled": True,
                            "auto_sync": False,
                            "root_only": True,
                        }
                    }
                }
            )
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        captured_fields: list = []

        def _capture(fields, console, **k):
            captured_fields.extend(fields)
            # Simulate cancel so we don't hit network.
            return None

        with patch("installer.flow.integration_config.run_form", side_effect=_capture):
            console = Console(width=80, force_terminal=False, no_color=True)
            configure_todoist(console)

        field_by_key = {f.key: f for f in captured_fields}
        assert field_by_key["api_token"].default == "existing-token"
        assert field_by_key["sync_enabled"].default is True
        assert field_by_key["auto_sync"].default is False
        assert field_by_key["root_only"].default is True

    def test_sync_disabled_skips_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """B2 fix: if user disables sync, empty creds OK + no API call."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        validator_called = {"n": 0}

        def _fake_validator(values):
            validator_called["n"] += 1
            return None

        # run_form returns submit with sync_enabled=False
        def _submit_sync_off(fields, console, **k):
            return {
                "api_token": "",
                "sync_enabled": False,
                "auto_sync": True,
                "root_only": False,
            }

        with (
            patch(
                "installer.flow.integration_config.run_form",
                side_effect=_submit_sync_off,
            ),
            patch(
                "installer.flow.integration_config._todoist_validator",
                side_effect=_fake_validator,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = configure_todoist(console)

        assert result is not None
        assert result["sync_enabled"] is False
        assert validator_called["n"] == 0

    def test_submit_with_valid_creds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        with (
            patch(
                "installer.flow.integration_config.run_form",
                return_value={
                    "api_token": "xyz",
                    "sync_enabled": True,
                    "auto_sync": True,
                    "root_only": False,
                },
            ),
            patch(
                "installer.flow.integration_config._todoist_validator",
                return_value=None,  # valid
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = configure_todoist(console)
        assert result == {
            "api_token": "xyz",
            "sync_enabled": True,
            "auto_sync": True,
            "root_only": False,
        }

    def test_validation_failure_reprompts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """On validator error, re-prompt with pre-filled values + error banner."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        # First call: bad token; second call: good token
        attempts = iter(
            [
                {
                    "api_token": "bad",
                    "sync_enabled": True,
                    "auto_sync": True,
                    "root_only": False,
                },
                {
                    "api_token": "good",
                    "sync_enabled": True,
                    "auto_sync": True,
                    "root_only": False,
                },
            ]
        )
        err_captured: list[str | None] = []

        def _fake_run_form(fields, console, *, title=None, error_message=None):
            err_captured.append(error_message)
            return next(attempts)

        validator_returns = iter(["invalid token", None])

        def _fake_validator(values):
            return next(validator_returns)

        with (
            patch(
                "installer.flow.integration_config.run_form",
                side_effect=_fake_run_form,
            ),
            patch(
                "installer.flow.integration_config._todoist_validator",
                side_effect=_fake_validator,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = configure_todoist(console)

        assert result is not None
        assert result["api_token"] == "good"
        # Second call should have error_message from first attempt
        assert err_captured[0] is None
        assert err_captured[1] == "invalid token"


class TestConfigureTrello:
    def test_cancel_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        with patch("installer.flow.integration_config.run_form", return_value=None):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = configure_trello(console)
        assert result is None

    def test_defaults_from_existing_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Existing creds in trello.yaml MUST pre-fill api_key + token."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "trello.yaml").write_text(
            yaml.safe_dump({"api_key": "existing-key", "token": "existing-token"})
        )
        (fake_home / ".claude" / "proj.yaml").write_text(
            yaml.safe_dump(
                {
                    "sync": {
                        "trello": {
                            "enabled": True,
                            "auto_sync": False,
                            "default_list": "MyList",
                            "on_delete": "delete",
                        }
                    }
                }
            )
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        captured: list = []

        def _capture(fields, console, **k):
            captured.extend(fields)
            return None

        with patch("installer.flow.integration_config.run_form", side_effect=_capture):
            console = Console(width=80, force_terminal=False, no_color=True)
            configure_trello(console)

        field_by_key = {f.key: f for f in captured}
        assert field_by_key["api_key"].default == "existing-key"
        assert field_by_key["token"].default == "existing-token"
        assert field_by_key["sync_enabled"].default is True
        assert field_by_key["auto_sync"].default is False
        assert field_by_key["default_list"].default == "MyList"
        assert field_by_key["on_delete"].default == "delete"
        # on_delete should be kind="select" with choices
        assert field_by_key["on_delete"].kind == "select"
        assert set(field_by_key["on_delete"].choices or []) == {"archive", "delete"}

    def test_sync_disabled_skips_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        validator_called = {"n": 0}

        def _fake_validator(values):
            validator_called["n"] += 1
            return None

        with (
            patch(
                "installer.flow.integration_config.run_form",
                return_value={
                    "api_key": "",
                    "token": "",
                    "sync_enabled": False,
                    "auto_sync": True,
                    "default_list": "Todo",
                    "on_delete": "archive",
                },
            ),
            patch(
                "installer.flow.integration_config._trello_validator",
                side_effect=_fake_validator,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = configure_trello(console)

        assert result is not None
        assert result["sync_enabled"] is False
        assert validator_called["n"] == 0

    def test_submit_with_valid_creds(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        with (
            patch(
                "installer.flow.integration_config.run_form",
                return_value={
                    "api_key": "k",
                    "token": "t",
                    "sync_enabled": True,
                    "auto_sync": True,
                    "default_list": "Todo",
                    "on_delete": "archive",
                },
            ),
            patch(
                "installer.flow.integration_config._trello_validator",
                return_value=None,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = configure_trello(console)
        assert result == {
            "api_key": "k",
            "token": "t",
            "sync_enabled": True,
            "auto_sync": True,
            "default_list": "Todo",
            "on_delete": "archive",
        }


class TestConfigureJira:
    def test_cancel_returns_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        with patch("installer.flow.integration_config.run_form", return_value=None):
            console = Console(width=80, force_terminal=False, no_color=True)
            assert configure_jira(console) is None

    def test_defaults_from_existing_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Existing creds in jira.yaml MUST pre-fill fields."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        (fake_home / ".claude" / "jira.yaml").write_text(
            yaml.safe_dump(
                {
                    "base_url": "https://co.atlassian.net",
                    "default_user": "u@example.com",
                    "personal_access_token": "pat-xyz",
                    "default_project": "PROJ",
                }
            )
        )
        (fake_home / ".claude" / "proj.yaml").write_text(
            yaml.safe_dump({"jira": {"enabled": True, "auto_sync": False}})
        )
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        captured: list = []

        def _capture(fields, console, **k):
            captured.extend(fields)
            return None

        with patch("installer.flow.integration_config.run_form", side_effect=_capture):
            console = Console(width=80, force_terminal=False, no_color=True)
            configure_jira(console)

        by_key = {f.key: f for f in captured}
        assert by_key["base_url"].default == "https://co.atlassian.net"
        assert by_key["default_user"].default == "u@example.com"
        assert by_key["personal_access_token"].default == "pat-xyz"
        assert by_key["default_project"].default == "PROJ"
        assert by_key["sync_enabled"].default is True
        assert by_key["auto_sync"].default is False

    def test_base_url_validator_rejects_bad_scheme(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """B1: base_url must start with http:// or https://."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        captured: list = []

        def _capture(fields, console, **k):
            captured.extend(fields)
            return None

        with patch("installer.flow.integration_config.run_form", side_effect=_capture):
            console = Console(width=80, force_terminal=False, no_color=True)
            configure_jira(console)

        base_url_field = [f for f in captured if f.key == "base_url"][0]
        assert base_url_field.validator is not None
        # Valid inputs
        assert base_url_field.validator("https://x.atlassian.net") is None
        assert base_url_field.validator("http://internal-jira") is None
        # Invalid inputs
        assert base_url_field.validator("ftp://bad") is not None
        assert base_url_field.validator("no-scheme.example.com") is not None
        assert base_url_field.validator("") is not None

    def test_trailing_slash_normalized_on_submit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """B3: trailing / stripped from base_url on submit."""
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)
        with (
            patch(
                "installer.flow.integration_config.run_form",
                return_value={
                    "base_url": "https://jira.example.com/",
                    "default_user": "u",
                    "personal_access_token": "t",
                    "default_project": "P",
                    "sync_enabled": True,
                    "auto_sync": True,
                },
            ),
            patch(
                "installer.flow.integration_config._jira_validator",
                return_value=None,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = configure_jira(console)
        assert result is not None
        assert result["base_url"] == "https://jira.example.com"  # no trailing slash

    def test_sync_disabled_skips_validation(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_home = tmp_path / "home"
        (fake_home / ".claude").mkdir(parents=True)
        monkeypatch.setattr("pathlib.Path.home", lambda: fake_home)

        validator_called = {"n": 0}

        def _fake_validator(values):
            validator_called["n"] += 1
            return None

        with (
            patch(
                "installer.flow.integration_config.run_form",
                return_value={
                    "base_url": "",
                    "default_user": "",
                    "personal_access_token": "",
                    "default_project": "",
                    "sync_enabled": False,
                    "auto_sync": True,
                },
            ),
            patch(
                "installer.flow.integration_config._jira_validator",
                side_effect=_fake_validator,
            ),
        ):
            console = Console(width=80, force_terminal=False, no_color=True)
            result = configure_jira(console)
        assert result is not None
        assert result["sync_enabled"] is False
        assert validator_called["n"] == 0
