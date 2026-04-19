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
from installer.flow.integration_config import (
    configure_jira,
    configure_todoist,
    configure_trello,
)
from installer.flow.plugin_select import select_plugin_actions
from installer.flow.pre_install_phase import pre_install_phase
from installer.flow.update import select_updates
from installer.flow.wizard import run_wizard
from installer.hooks_diff import apply_diffs, compute_hooks_diff
from installer.plugin_cli import (
    add_marketplace,
    check_marketplace_registered,
    get_available_plugins,
    get_installed_plugins,
)
from installer.plugin_status import build_plugin_status_list
from installer.update import compare_versions

_WIZARD_PLUGINS = {"proj", "router", "todoist", "trello", "jira", "worktree"}


class _WizardState:
    """Lightweight state passed to run_wizard. Only installed_plugins is read."""

    def __init__(self, installed_plugins: list[str]) -> None:
        self.installed_plugins = installed_plugins


def _write_wizard_result(result: dict[str, Any]) -> None:
    """Write wizard dict to bucket-partitioned yaml files."""
    from installer._config_loader import load_existing_yaml
    from installer._config_writer import partition_answers_by_bucket, write_bucket

    buckets = partition_answers_by_bucket(result)
    claude_home = Path.home() / ".claude"
    for bucket_name, answers in buckets.items():
        if not answers:
            continue
        path = claude_home / f"{bucket_name}.yaml"
        try:
            existing = load_existing_yaml(path) if path.exists() else {}
        except Exception:
            existing = {}
        write_bucket(path, existing, answers, bucket=bucket_name)


def _write_integration_result(service: str, result: dict[str, Any]) -> None:
    """Split result dict into credential yaml + proj.yaml sync section.

    Uses write_bucket for both writes: fcntl.flock + atomic tmp+rename +
    TOCTOU drift detection.
    """
    from installer._config_loader import load_existing_yaml
    from installer._config_writer import write_bucket

    claude_home = Path.home() / ".claude"
    service_yaml = claude_home / f"{service}.yaml"
    proj_yaml = claude_home / "proj.yaml"

    CRED_FIELDS: dict[str, list[str]] = {
        "todoist": ["api_token"],
        "trello": ["api_key", "token"],
        "jira": [
            "base_url",
            "default_user",
            "personal_access_token",
            "default_project",
        ],
    }
    # Dotted-key prefix for sync settings in proj.yaml.
    # Jira uses top-level "jira.<field>"; Todoist/Trello use "sync.<service>.<field>".
    SYNC_PREFIX: dict[str, str] = {
        "todoist": "sync.todoist",
        "trello": "sync.trello",
        "jira": "jira",
    }
    SYNC_FIELDS: dict[str, list[str]] = {
        "todoist": ["enabled", "auto_sync", "root_only"],
        "trello": ["enabled", "auto_sync", "default_list", "on_delete"],
        "jira": ["enabled", "auto_sync"],
    }

    # Build credential answers dict (flat, non-dotted — service yaml is flat)
    cred_answers: dict[str, Any] = {
        field: result[field] for field in CRED_FIELDS[service] if field in result
    }
    if cred_answers:
        try:
            existing_service = (
                load_existing_yaml(service_yaml) if service_yaml.exists() else {}
            )
        except Exception:
            existing_service = {}
        write_bucket(service_yaml, existing_service, cred_answers, bucket=service)

    # Build dotted-key answers for proj.yaml sync section
    prefix = SYNC_PREFIX[service]
    proj_answers: dict[str, Any] = {}
    for field in SYNC_FIELDS[service]:
        # sync_enabled in result → "enabled" in yaml
        src_key = "sync_enabled" if field == "enabled" else field
        if src_key in result:
            proj_answers[f"{prefix}.{field}"] = result[src_key]
    if proj_answers:
        try:
            existing_proj = load_existing_yaml(proj_yaml) if proj_yaml.exists() else {}
        except Exception:
            existing_proj = {}
        write_bucket(proj_yaml, existing_proj, proj_answers, bucket="proj")


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

    # 2a. Run wizard if any proj-relevant plugins selected
    selected_names = [name for name, _action in actions]
    if any(name in _WIZARD_PLUGINS for name in selected_names):
        wizard_state = _WizardState(installed_plugins=selected_names)
        wizard_result = run_wizard(wizard_state, args, console)
        if wizard_result is None:
            console.print("[dim]Cancelled at wizard.[/dim]")
            return 0
        _write_wizard_result(wizard_result)

    # 2b. Run integration configs for selected integration plugins
    for service, configure_fn in (
        ("todoist", configure_todoist),
        ("trello", configure_trello),
        ("jira", configure_jira),
    ):
        if service not in selected_names:
            continue
        result = configure_fn(console)
        if result is None:
            console.print(f"[dim]Cancelled at {service} config.[/dim]")
            return 0
        _write_integration_result(service, result)

    hooks_yaml = Path.home() / ".claude" / "hooks.yaml"
    # Resolve plugin dirs from selected plugin names so compute_hooks_diff can
    # read each plugin's default-hooks.yaml.  Passing [] would cause
    # merge_defaults to return {} and show every hook as "to remove".
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
