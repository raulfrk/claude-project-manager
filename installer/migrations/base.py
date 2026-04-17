from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from pathlib import Path

from installer.migrations.types import MigrationState

log = logging.getLogger(__name__)


class InvalidTransition(RuntimeError):
    """Attempted state transition not allowed by the state machine."""


ALLOWED: dict[MigrationState, set[MigrationState]] = {
    MigrationState.DISCOVERED: {MigrationState.PLANNED},
    MigrationState.PLANNED: {MigrationState.CONFIRMED, MigrationState.SKIPPED},
    MigrationState.CONFIRMED: {MigrationState.BACKED_UP},
    MigrationState.SKIPPED: set(),
    MigrationState.BACKED_UP: {MigrationState.FLATTENED, MigrationState.RESTORING},
    MigrationState.FLATTENED: {MigrationState.RESYNCED, MigrationState.RESTORING},
    MigrationState.RESYNCED: {MigrationState.COMMITTED, MigrationState.RESTORING},
    MigrationState.COMMITTED: {MigrationState.CLEANED, MigrationState.RESTORING},
    MigrationState.CLEANED: set(),
    MigrationState.RESTORING: {MigrationState.FAILED},
    MigrationState.FAILED: set(),
}


@dataclass
class MigrationRunner(abc.ABC):
    project_name: str
    project_dir: Path
    state: MigrationState = MigrationState.DISCOVERED
    history: list[MigrationState] = field(default_factory=list)

    def transition(self, target: MigrationState) -> None:
        if target not in ALLOWED[self.state]:
            raise InvalidTransition(
                f"{self.project_name}: cannot move {self.state.value} → {target.value}",
            )
        log.debug("%s: %s → %s", self.project_name, self.state.value, target.value)
        self.history.append(self.state)
        self.state = target

    @abc.abstractmethod
    def _plan(self) -> None: ...

    @abc.abstractmethod
    def _backup(self) -> None: ...

    @abc.abstractmethod
    def _flatten(self) -> None: ...

    @abc.abstractmethod
    def _resync(self) -> None: ...

    @abc.abstractmethod
    def _commit(self) -> None: ...

    @abc.abstractmethod
    def _restore(self) -> None: ...
