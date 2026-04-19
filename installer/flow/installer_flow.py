# installer/flow/installer_flow.py
"""Top-level installer flow dispatcher.

Replaces InstallerApp().run(). Orchestrates the 3-phase flow:
  1. pre_install_phase (Rich): detection, confirms
  2. interactive phase: Rich/prompt_toolkit prompts OR plain plan-build
  3. execution phase: Rich progress + cleanup
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from claudemd import ensure_managed_section, remove_managed_section
from rich.console import Console

from installer.cleanup import (
    cleanup_orphaned_plugin_caches,
    prune_orphaned_plugins,
)
from installer.errors import InstallerError
from installer.flow.hooks_diff import review_hooks_diff
from installer.flow.install_plan import (
    InstallAction,
    InstallPlan,
    execute_install_plan,
)
from installer.flow.plugin_select import select_plugin_actions
from installer.flow.pre_install_phase import pre_install_phase
from installer.flow.update import select_updates
from installer.hooks_diff import apply_diffs, compute_hooks_diff
from installer.plugin_cli import (
    add_marketplace,
    check_marketplace_registered,
    get_available_plugins,
    get_installed_plugins,
)
from installer.plugin_status import build_plugin_status_list
from installer.update import compare_versions


def _name_to_id_map() -> dict[str, str]:
    try:
        available = get_available_plugins()
        installed_ids = get_installed_plugins()
    except InstallerError:
        available, installed_ids = [], []
    name_to_id: dict[str, str] = {}
    for pid in list(available) + list(installed_ids):
        name_to_id.setdefault(pid.split("@")[0], pid)
    return name_to_id


def _resolve_id(name: str, name_to_id: dict[str, str]) -> str:
    return name_to_id.get(name, f"{name}@claude-project-manager")


def _execute_and_report(plan: InstallPlan, console: Console) -> int:
    result = execute_install_plan(plan, console)
    if result.failure_count:
        for failure in result.failures:
            console.print(
                f"[red]✗[/] {failure.plugin_id} ({failure.action}): {failure.error}"
            )
        return 1
    return 0


def _post_execute_cleanup(
    full_cleanup: bool, orphans: list[str], console: Console
) -> None:
    cache_root = Path.home() / ".claude" / "plugins" / "cache"
    installed_json = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        cleanup_orphaned_plugin_caches(cache_root, installed_json)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    if orphans:
        prune_orphaned_plugins(cache_root, orphans)
    if full_cleanup:
        remove_managed_section(Path.home() / ".claude" / "CLAUDE.md")


def _resolve_plugin_dirs(plugin_names: list[str]) -> list[Path]:
    """Resolve highest-version cache dirs for each selected plugin name.

    Mirrors app.py::_check_hooks_diff which called wizard._resolve_plugin_dir
    per selected plugin.  Without this, compute_hooks_diff receives an empty
    list → merge_defaults returns {} → diff treats every hook as "to remove".
    """
    from installer.wizard import _resolve_plugin_dir

    cache_dir = Path.home() / ".claude" / "plugins" / "cache" / "claude-project-manager"
    dirs: list[Path] = []
    for name in plugin_names:
        resolved = _resolve_plugin_dir(cache_dir, name)
        if resolved is not None:
            dirs.append(resolved)
    return dirs


def _run_install(args: Any, console: Console) -> int:
    if not check_marketplace_registered():
        console.print("[yellow]Marketplace not registered — registering...[/]")
        try:
            branch = getattr(args, "branch", None)
            add_marketplace(branch=branch)
        except InstallerError as exc:
            console.print(f"[red]Failed to register marketplace:[/] {exc}")
            return 1

    statuses = build_plugin_status_list()
    actions = select_plugin_actions(statuses, console)
    if not actions:
        console.print("[dim]No actions selected.[/dim]")
        return 0

    hooks_yaml = Path.home() / ".claude" / "hooks.yaml"
    # Resolve plugin dirs from selected plugin names so compute_hooks_diff can
    # read each plugin's default-hooks.yaml.  Passing [] would cause
    # merge_defaults to return {} and show every hook as "to remove".
    selected_names = [name for name, _action in actions]
    plugin_dirs = _resolve_plugin_dirs(selected_names)
    diffs = compute_hooks_diff(hooks_yaml, plugin_dirs)

    # NOTE — Issue 2 (resync runbook): _emit_resync_runbooks in app.py is
    # migrate-specific: it takes migration runner objects with resync_failures
    # (Todoist api_token errors) and MigrationOutcome lists.  InstallResult
    # carries plain FailureRecord objects (plugin install errors) — a completely
    # different shape.  No runbook emission applies to the install/update/
    # reinstall/uninstall flows.  Deferred: migrate-only concern, documented here.

    # NOTE — Issue 3 (review_config_diff): in pre-P3, ConfigDiffScreen ran
    # inside the Textual integration-config wizard (integration_config.py) after
    # the user filled in credentials.  The Rich replacement (flow/config_diff.py
    # review_config_diff) is defined but has no call site here because the P3
    # install flow does not run the integration wizard — plugin installs happen
    # without touching service configs.  Wiring review_config_diff requires
    # porting the full integration wizard to Rich, which is out of scope for P3.
    # Deferred: needs a Rich integration-wizard port before it can be called.
    decision = review_hooks_diff(diffs, console)
    if decision is None:
        console.print("[dim]Cancelled at hooks review.[/dim]")
        return 0
    if decision["apply"] or decision["remove"]:
        apply_diffs(hooks_yaml, diffs, decision["apply"], decision["remove"])

    ensure_managed_section(Path.home() / ".claude" / "CLAUDE.md")

    name_to_id = _name_to_id_map()
    plan_actions = [
        InstallAction(
            plugin_id=_resolve_id(name, name_to_id),
            action=action,  # type: ignore[arg-type]
        )
        for name, action in actions
    ]
    plan = InstallPlan(
        description=f"Processing {len(plan_actions)} plugin actions...",
        actions=plan_actions,
    )
    exit_code = _execute_and_report(plan, console)
    _post_execute_cleanup(full_cleanup=False, orphans=[], console=console)
    return exit_code


def _run_update(args: Any, pre_state: Any, console: Console) -> int:
    diffs = compare_versions(pre_state)
    if not diffs:
        console.print("[dim]All plugins are up to date.[/dim]")
        return 0
    selected = select_updates(diffs, console)
    if not selected:
        console.print("[dim]No updates selected.[/dim]")
        return 0
    name_to_id = _name_to_id_map()
    plan_actions = [
        InstallAction(
            plugin_id=_resolve_id(name, name_to_id),
            action="update",
        )
        for name in selected
    ]
    plan = InstallPlan(
        description=f"Updating {len(plan_actions)} plugins...",
        actions=plan_actions,
    )
    exit_code = _execute_and_report(plan, console)
    _post_execute_cleanup(full_cleanup=False, orphans=[], console=console)
    return exit_code


def _run_reinstall(
    args: Any,
    pre_state: Any,
    mode_options: dict[str, bool],
    orphans: list[str],
    console: Console,
) -> int:
    installed_names = list(pre_state.installed_plugins) if pre_state else []
    if not installed_names:
        console.print("[dim]Nothing to reinstall.[/dim]")
        return 0
    name_to_id = _name_to_id_map()
    plan_actions = [
        InstallAction(plugin_id=_resolve_id(n, name_to_id), action="reinstall")
        for n in installed_names
    ]
    plan = InstallPlan(
        description=f"Reinstalling {len(plan_actions)} plugins...",
        actions=plan_actions,
    )
    exit_code = _execute_and_report(plan, console)
    _post_execute_cleanup(full_cleanup=False, orphans=orphans, console=console)
    return exit_code


def _run_uninstall(
    args: Any,
    pre_state: Any,
    mode_options: dict[str, bool],
    console: Console,
) -> int:
    installed_names = list(pre_state.installed_plugins) if pre_state else []
    if not installed_names:
        console.print("[dim]Nothing to uninstall.[/dim]")
        return 0
    name_to_id = _name_to_id_map()
    plan_actions = [
        InstallAction(plugin_id=_resolve_id(n, name_to_id), action="uninstall")
        for n in installed_names
    ]
    plan = InstallPlan(
        description=f"Uninstalling {len(plan_actions)} plugins...",
        actions=plan_actions,
    )
    exit_code = _execute_and_report(plan, console)
    _post_execute_cleanup(
        full_cleanup=mode_options.get("full_cleanup", False),
        orphans=[],
        console=console,
    )
    return exit_code


def run_installer_flow(mode: str, args: Any, console: Console) -> int:
    """Top-level dispatcher: pre-install → mode dispatch → cleanup."""
    pre = pre_install_phase(mode, args, console)
    if not pre.proceed:
        if pre.error_message:
            console.print(pre.error_message)
        return pre.exit_code

    if mode == "install":
        return _run_install(args, console)
    if mode == "update":
        return _run_update(args, pre.state, console)
    if mode == "reinstall":
        return _run_reinstall(
            args, pre.state, pre.mode_options, pre.orphans_to_remove, console
        )
    if mode == "uninstall":
        return _run_uninstall(args, pre.state, pre.mode_options, console)

    console.print(f"[red]Unknown mode: {mode}[/red]")
    return 2
