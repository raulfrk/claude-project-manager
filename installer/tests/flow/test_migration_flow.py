# installer/tests/flow/test_migration_flow.py
from pathlib import Path

import pytest
from rich.console import Console

from installer.flow.migration_flow import (
    prompt_migration_action,
    prompt_migration_review,
    show_dry_run_preview,
)
from installer.migrations.types import MigrationPlan, PendingProject, TodoRef


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


def _make_plan() -> MigrationPlan:
    parent = TodoRef(id="1", title="parent")
    c1 = TodoRef(id="1.1", title="c1", parent="1")
    c2 = TodoRef(id="1.2", title="c2", parent="1")
    return MigrationPlan(
        project=_p("alpha"),
        parents=[parent],
        children=[c1, c2],
        integration_actions={"todoist": [], "trello": []},
    )


class TestPromptMigrationReview:
    def test_migrate_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # First prompt -> 'm', confirm dialog -> 'y'.
        calls = iter(["m", "y"])
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: next(calls))
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = prompt_migration_review(
            plan=_make_plan(),
            backup_preview="/tmp/backup/alpha",
            console=console,
        )
        assert result == "migrate"

    def test_migrate_declined_maps_to_skip(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = iter(["m", "n"])
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: next(calls))
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = prompt_migration_review(
            plan=_make_plan(),
            backup_preview="/tmp/backup/alpha",
            console=console,
        )
        assert result == "skip"

    def test_skip_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "s")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert (
            prompt_migration_review(
                plan=_make_plan(), backup_preview="/tmp/bk/alpha", console=console
            )
            == "skip"
        )

    def test_quit_choice(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: "q")
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        assert (
            prompt_migration_review(
                plan=_make_plan(), backup_preview="/tmp/bk/alpha", console=console
            )
            == "quit"
        )

    def test_dry_run_then_migrate(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # First prompt -> 'd' (dry-run), then Press Enter (empty), then 'm' at the
        # main prompt again, then 'y' at confirm.
        calls = iter(["d", "", "m", "y"])
        monkeypatch.setattr("rich.prompt.Prompt.ask", lambda *a, **k: next(calls))
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        result = prompt_migration_review(
            plan=_make_plan(),
            backup_preview="/tmp/bk/alpha",
            console=console,
        )
        assert result == "migrate"


class TestShowDryRunPreview:
    def test_renders_plan(self) -> None:
        console = Console(record=True, width=80, force_terminal=False, no_color=True)
        show_dry_run_preview(_make_plan(), console)
        text = console.export_text()
        assert "children" in text.lower() or "1.1" in text
        assert "todoist" in text.lower() or "trello" in text.lower()
