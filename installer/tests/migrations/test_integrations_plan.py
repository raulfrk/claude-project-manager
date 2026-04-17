# installer/tests/migrations/test_integrations_plan.py
from __future__ import annotations

from installer.migrations.integrations.base import Action, ResyncResult


def test_action_is_frozen_dataclass() -> None:
    a = Action(kind="clear_parent", target_id="abc", payload={})
    import dataclasses

    with __import__("pytest").raises(dataclasses.FrozenInstanceError):
        a.kind = "other"  # type: ignore[misc]


def test_resyncresult_defaults() -> None:
    r = ResyncResult()
    assert r.ok == []
    assert r.failed == []
    assert r.aborted is False
