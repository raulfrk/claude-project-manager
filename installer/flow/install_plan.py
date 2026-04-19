# installer/flow/install_plan.py
"""Install-action plan + executor.

Split off from the Textual worker model so the side-effect phase can run
outside a Textual App (Textual owns the terminal; Rich progress needs it).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
)

from installer.errors import InstallerError
from installer.plugin_cli import install_plugin, uninstall_plugin


Action = Literal["install", "uninstall", "reinstall"]


@dataclass(frozen=True)
class InstallAction:
    plugin_id: str  # fully qualified, e.g. "proj@claude-project-manager"
    action: Action


@dataclass(frozen=True)
class InstallFailure:
    plugin_id: str
    action: Action
    error: str


@dataclass
class InstallResult:
    success_count: int = 0
    failure_count: int = 0
    failures: list[InstallFailure] = field(default_factory=list)


@dataclass(frozen=True)
class InstallPlan:
    description: str
    actions: list[InstallAction]


def execute_install_plan(plan: InstallPlan, console: Console) -> InstallResult:
    """Run each action in the plan, updating a Rich progress bar.

    Catches ``InstallerError`` per action so one failure doesn't abort the batch.
    """
    result = InstallResult()
    total = len(plan.actions)
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task(plan.description, total=total)
        for action in plan.actions:
            progress.update(
                task,
                description=f"{action.action.capitalize()}ing {action.plugin_id}...",
            )
            try:
                if action.action == "install":
                    install_plugin(action.plugin_id)
                elif action.action == "uninstall":
                    uninstall_plugin(action.plugin_id)
                elif action.action == "reinstall":
                    uninstall_plugin(action.plugin_id)
                    install_plugin(action.plugin_id)
                result.success_count += 1
            except InstallerError as exc:
                result.failures.append(
                    InstallFailure(
                        plugin_id=action.plugin_id,
                        action=action.action,
                        error=str(exc),
                    ),
                )
                result.failure_count += 1
            progress.advance(task)
    return result
