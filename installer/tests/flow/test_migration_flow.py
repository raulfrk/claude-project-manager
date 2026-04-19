# installer/tests/flow/test_migration_flow.py
from pathlib import Path

import pytest
from rich.console import Console

from installer.flow.migration_flow import prompt_migration_action
from installer.migrations.types import PendingProject


def _p(name: str) -> PendingProject:
    return PendingProject(
        name=name,
        path=Path("/tmp") / name,
        schema_version_path=Path("/tmp") / name / ".schema-version",
        current_version=1,
    )


class TestPromptMigrationAction:
    def test_review_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "r")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = prompt_migration_action(
            pending=[_p("alpha"), _p("beta")],
            integration_map={"alpha": {"todoist"}, "beta": set()},
            counts={"alpha": (2, 3), "beta": (0, 0)},
            console=console,
        )
        assert result == "review"

    def test_skip_all_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "s")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = prompt_migration_action(
            pending=[_p("alpha")],
            integration_map={"alpha": set()},
            counts={"alpha": (1, 0)},
            console=console,
        )
        assert result == "skip_all"

    def test_quit_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "q")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = prompt_migration_action(
            pending=[_p("alpha")],
            integration_map={"alpha": set()},
            counts={"alpha": (1, 0)},
            console=console,
        )
        assert result == "quit"

    def test_table_rendered_with_project_data(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "q")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        prompt_migration_action(
            pending=[_p("alpha"), _p("beta")],
            integration_map={"alpha": {"todoist", "trello"}, "beta": set()},
            counts={"alpha": (2, 3), "beta": (0, 0)},
            console=console,
        )
        text = console.export_text()
        assert "alpha" in text
        assert "beta" in text
        assert "2" in text  # parents column
        assert "3" in text  # children column
        assert "todoist" in text or "trello" in text
