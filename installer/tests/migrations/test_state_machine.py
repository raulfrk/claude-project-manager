from __future__ import annotations

from pathlib import Path

import pytest

from installer.migrations.base import InvalidTransition, MigrationRunner
from installer.migrations.types import MigrationState


class FakeRunner(MigrationRunner):
    def _plan(self): ...
    def _backup(self): ...
    def _flatten(self): ...
    def _resync(self): ...
    def _commit(self): ...
    def _restore(self): ...


def test_valid_transition_sequence(tmp_path: Path) -> None:
    r = FakeRunner(project_name="demo", project_dir=tmp_path)
    assert r.state == MigrationState.DISCOVERED
    r.transition(MigrationState.PLANNED)
    r.transition(MigrationState.CONFIRMED)
    r.transition(MigrationState.BACKED_UP)
    r.transition(MigrationState.FLATTENED)
    r.transition(MigrationState.RESYNCED)
    r.transition(MigrationState.COMMITTED)
    r.transition(MigrationState.CLEANED)


def test_invalid_transition_raises(tmp_path: Path) -> None:
    r = FakeRunner(project_name="demo", project_dir=tmp_path)
    with pytest.raises(InvalidTransition):
        r.transition(MigrationState.COMMITTED)  # skip phases


def test_skip_branch(tmp_path: Path) -> None:
    r = FakeRunner(project_name="demo", project_dir=tmp_path)
    r.transition(MigrationState.PLANNED)
    r.transition(MigrationState.SKIPPED)
    with pytest.raises(InvalidTransition):
        r.transition(MigrationState.BACKED_UP)


def test_restoring_allowed_from_post_backup_states(tmp_path: Path) -> None:
    for from_state in (
        MigrationState.FLATTENED,
        MigrationState.RESYNCED,
        MigrationState.COMMITTED,
    ):
        r = FakeRunner(project_name="demo", project_dir=tmp_path)
        for s in (
            MigrationState.PLANNED,
            MigrationState.CONFIRMED,
            MigrationState.BACKED_UP,
        ):
            r.transition(s)
        # climb to target then test restore path
        if from_state != MigrationState.BACKED_UP:
            r.transition(MigrationState.FLATTENED)
        if from_state == MigrationState.RESYNCED:
            r.transition(MigrationState.RESYNCED)
        if from_state == MigrationState.COMMITTED:
            r.transition(MigrationState.RESYNCED)
            r.transition(MigrationState.COMMITTED)
        r.transition(MigrationState.RESTORING)
        r.transition(MigrationState.FAILED)
