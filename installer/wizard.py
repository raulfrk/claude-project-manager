"""Post-install setup wizard."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.prompt import Confirm, Prompt

from installer._config_loader import ConfigLoadError, get_nested, load_existing_yaml
from installer.claudemd import ensure_managed_section
from installer.hooks_diff import apply_diffs, compute_hooks_diff
from installer.prompts import int_in_range, prompt_choice
from installer.wizard_specs import PROJ_YAML_PROMPTS, PromptSpec


def _resolve_plugin_dir(cache_dir: Path, plugin_name: str) -> Path | None:
    """Return the highest-version subdir of cache_dir/plugin_name, or None.

    Uses natural-version ordering via `packaging.version.Version` if available,
    otherwise falls back to lexicographic sort on subdir names.
    """
    plugin_root = cache_dir / plugin_name
    if not plugin_root.is_dir():
        return None
    versions = [p for p in plugin_root.iterdir() if p.is_dir()]
    if not versions:
        return None
    try:
        from packaging.version import Version  # type: ignore[import-not-found]

        def key(p: Path) -> Version:
            try:
                return Version(p.name)
            except Exception:
                return Version("0")

        return max(versions, key=key)
    except Exception:
        return max(versions, key=lambda p: p.name)


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


def _merge_dotted_into_dict(
    existing: dict[str, Any], answers: dict[str, Any]
) -> dict[str, Any]:
    """Merge flat dotted-key answers into a nested existing dict (in-place + return).

    Preserves unknown keys in existing. Creates intermediate dicts as needed.
    """
    for dotted, value in answers.items():
        parts = dotted.split(".")
        cursor = existing
        for segment in parts[:-1]:
            nxt = cursor.get(segment)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[segment] = nxt
            cursor = nxt
        cursor[parts[-1]] = value
    return existing


def _masked_default(value: str, min_len: int = 8) -> str:
    """Return a masked preview of a credential value for display as a prompt default."""
    if not value:
        return ""
    if len(value) < min_len:
        return "****"
    return f"****{value[-4:]}"


def _dispatch_rich_prompt(spec: PromptSpec, default: Any, console: Console) -> Any:
    """Dispatch a PromptSpec to the correct Rich prompt type."""
    try:
        if spec.type == "bool":
            return Confirm.ask(spec.label, default=bool(default), console=console)
        if spec.type == "str":
            return Prompt.ask(
                spec.label,
                default="" if default is None else str(default),
                console=console,
            )
        if spec.type == "int":
            if spec.int_range is None:
                raise ValueError(
                    f"PromptSpec {spec.dotted_key!r} has type=int but no int_range"
                )
            low, high = spec.int_range
            try:
                int_default = int(default)
            except (TypeError, ValueError):
                int_default = low
            return int_in_range(spec.label, int_default, low, high, console)
        if spec.type == "choice":
            if not spec.choices:
                raise ValueError(
                    f"PromptSpec {spec.dotted_key!r} has type=choice but no choices"
                )
            return prompt_choice(spec.label, str(default), spec.choices, console)
        raise ValueError(f"Unknown PromptSpec type: {spec.type!r}")
    except EOFError:
        return default


def _render_prompts_rich(
    specs: list[PromptSpec],
    existing: dict[str, Any],
    console: Console,
    tier: str,
    yaml_file: str,
) -> dict[str, Any]:
    """Iterate PromptSpec entries filtered by tier+yaml_file, honor conditions, emit group headers."""
    answers: dict[str, Any] = {}
    current_group: str | None = None
    for spec in specs:
        if spec.yaml_file != yaml_file:
            continue
        if spec.tier != tier:
            continue
        if spec.condition is not None:
            merged_view = dict(existing)
            _merge_dotted_into_dict(merged_view, answers)
            if not spec.condition(merged_view):
                continue
        if spec.group != current_group:
            console.print(f"\n[bold cyan]── {spec.group} ──[/bold cyan]")
            current_group = spec.group
        default = spec.default_factory(existing)
        answers[spec.dotted_key] = _dispatch_rich_prompt(spec, default, console)
    return answers


def _setup_proj_yaml(console: Console, selected_plugins: list[str]) -> dict[str, Any]:
    """Setup ~/.claude/proj.yaml using PromptSpec table. Returns final config dict."""
    del selected_plugins  # plugin gating is now handled via PromptSpec conditions
    path = Path.home() / ".claude" / "proj.yaml"
    try:
        existing = load_existing_yaml(path)
    except ConfigLoadError as exc:
        console.print(f"[red]Failed to load {path}: {exc.original}[/red]")
        console.print("[yellow]Aborting proj.yaml setup.[/yellow]")
        return {}
    mtime_before = path.stat().st_mtime if path.exists() else None

    console.print("\n[bold]proj.yaml configuration[/bold]")

    basic_answers = _render_prompts_rich(
        PROJ_YAML_PROMPTS, existing, console, tier="basic", yaml_file="proj"
    )
    _merge_dotted_into_dict(existing, basic_answers)

    if Confirm.ask("\nShow advanced options?", default=False, console=console):
        advanced_answers = _render_prompts_rich(
            PROJ_YAML_PROMPTS, existing, console, tier="advanced", yaml_file="proj"
        )
        _merge_dotted_into_dict(existing, advanced_answers)

    if (
        mtime_before is not None
        and path.exists()
        and path.stat().st_mtime != mtime_before
    ):
        console.print(
            "[red]proj.yaml changed on disk during wizard — aborting write.[/red]"
        )
        return existing

    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        path, yaml.safe_dump(existing, sort_keys=False, default_flow_style=False)
    )
    console.print(f"[green]Wrote {path}[/green]")
    return existing


def _setup_worktree_yaml(console: Console) -> dict[str, Any]:
    """Setup ~/.claude/worktree.yaml using PromptSpec table. Returns final config dict."""
    path = Path.home() / ".claude" / "worktree.yaml"
    try:
        existing = load_existing_yaml(path)
    except ConfigLoadError as exc:
        console.print(f"[red]Failed to load {path}: {exc.original}[/red]")
        console.print("[yellow]Aborting worktree.yaml setup.[/yellow]")
        return {}
    mtime_before = path.stat().st_mtime if path.exists() else None

    console.print("\n[bold]worktree.yaml configuration[/bold]")

    basic_answers = _render_prompts_rich(
        PROJ_YAML_PROMPTS, existing, console, tier="basic", yaml_file="worktree"
    )
    _merge_dotted_into_dict(existing, basic_answers)

    if Confirm.ask("\nShow advanced options?", default=False, console=console):
        advanced_answers = _render_prompts_rich(
            PROJ_YAML_PROMPTS, existing, console, tier="advanced", yaml_file="worktree"
        )
        _merge_dotted_into_dict(existing, advanced_answers)

    if (
        mtime_before is not None
        and path.exists()
        and path.stat().st_mtime != mtime_before
    ):
        console.print(
            "[red]worktree.yaml changed on disk during wizard — aborting write.[/red]"
        )
        return existing

    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(
        path, yaml.safe_dump(existing, sort_keys=False, default_flow_style=False)
    )
    console.print(f"[green]Wrote {path}[/green]")
    return existing


def _hooks_diff_prompt(plugin_dirs: list[Path], console: Console | None = None) -> None:
    """Show hooks.yaml diff and prompt per-hook in Rich (--no-tui path)."""
    if console is None:
        console = Console()

    hooks_path = Path.home() / ".claude" / "hooks.yaml"
    diffs = compute_hooks_diff(hooks_path, plugin_dirs)

    if not diffs:
        console.print("[dim]hooks.yaml is up to date.[/dim]")
        return

    console.print(
        f"\n[bold]Hook Configuration Updates[/bold] — {len(diffs)} change(s)\n"
    )

    apply_ids: set[str] = set()
    remove_ids: set[str] = set()

    badge_map = {
        "new": "[green]NEW[/green]",
        "changed": "[yellow]CHANGED[/yellow]",
        "removed": "[red]REMOVED[/red]",
    }

    for diff in diffs:
        badge = badge_map.get(diff.status, diff.status)
        console.print(f"  {badge}  [bold]{diff.hook_id}[/bold]")
        if diff.unified_diff:
            console.print(diff.unified_diff)
        default = diff.status != "removed"
        action = Confirm.ask("  Apply this change?", default=default, console=console)
        if action and diff.status == "removed":
            remove_ids.add(diff.hook_id)
        elif action:
            apply_ids.add(diff.hook_id)

    if apply_ids or remove_ids:
        apply_diffs(hooks_path, diffs, apply_ids, remove_ids)
        console.print(
            f"\n[green]Applied {len(apply_ids)} update(s), "
            f"removed {len(remove_ids)} hook(s).[/green]"
        )
    else:
        console.print("\n[dim]No hook changes applied.[/dim]")


def _setup_todoist_config(console: Console) -> None:
    """Prompt for Todoist config in Rich (--no-tui path)."""
    config_path = Path.home() / ".claude" / "todoist.yaml"
    try:
        existing = load_existing_yaml(config_path)
    except ConfigLoadError as exc:
        console.print(f"[red]Failed to load {config_path}: {exc.original}[/red]")
        return

    console.print("\n[bold]Todoist Configuration[/bold]")

    enabled = Confirm.ask(
        "Enable Todoist sync?",
        default=bool(get_nested(existing, "enabled", False)),
        console=console,
    )
    if not enabled:
        console.print("[dim]Skipping Todoist configuration.[/dim]")
        return

    auto_sync = Confirm.ask(
        "Enable auto-sync?",
        default=bool(get_nested(existing, "auto_sync", True)),
        console=console,
    )

    existing_token = str(get_nested(existing, "api_token", "") or "")
    token_input = Prompt.ask(
        "Todoist API token",
        password=True,
        default=_masked_default(existing_token),
        console=console,
    )
    if token_input == _masked_default(existing_token) and existing_token:
        api_token = existing_token
    else:
        api_token = token_input

    if not api_token.strip():
        console.print("[red]API token is required.[/red]")
        return

    import httpx

    try:
        resp = httpx.get(
            "https://api.todoist.com/api/v1/projects",
            headers={"Authorization": f"Bearer {api_token}"},
            timeout=10,
        )
        if resp.status_code == 401:
            console.print("[red]Invalid API token.[/red]")
            return
        if resp.status_code != 200:
            console.print(f"[red]Todoist API error: {resp.status_code}[/red]")
            return
    except httpx.ConnectError:
        console.print("[red]Cannot reach Todoist API — check network.[/red]")
        return
    except httpx.TimeoutException:
        console.print("[red]Todoist API timeout.[/red]")
        return

    _atomic_write(
        config_path,
        yaml.dump(
            {"api_token": api_token.strip(), "enabled": True, "auto_sync": auto_sync},
            default_flow_style=False,
            sort_keys=False,
        ),
    )
    console.print(f"[green]Todoist configured — wrote {config_path}[/green]")


def _setup_trello_config(console: Console) -> None:
    """Prompt for Trello config in Rich (--no-tui path)."""
    config_path = Path.home() / ".claude" / "trello.yaml"
    try:
        existing = load_existing_yaml(config_path)
    except ConfigLoadError as exc:
        console.print(f"[red]Failed to load {config_path}: {exc.original}[/red]")
        return

    console.print("\n[bold]Trello Configuration[/bold]")

    enabled = Confirm.ask(
        "Enable Trello sync?",
        default=bool(get_nested(existing, "enabled", False)),
        console=console,
    )
    if not enabled:
        console.print("[dim]Skipping Trello configuration.[/dim]")
        return

    auto_sync = Confirm.ask(
        "Enable auto-sync?",
        default=bool(get_nested(existing, "auto_sync", True)),
        console=console,
    )

    existing_key = str(get_nested(existing, "api_key", "") or "")
    key_input = Prompt.ask(
        "Trello API key",
        password=True,
        default=_masked_default(existing_key),
        console=console,
    )
    api_key = (
        existing_key
        if key_input == _masked_default(existing_key) and existing_key
        else key_input
    )

    existing_token = str(get_nested(existing, "token", "") or "")
    token_input = Prompt.ask(
        "Trello token",
        password=True,
        default=_masked_default(existing_token),
        console=console,
    )
    token = (
        existing_token
        if token_input == _masked_default(existing_token) and existing_token
        else token_input
    )

    if not api_key.strip() or not token.strip():
        console.print("[red]API key and token are both required.[/red]")
        return

    default_board_id = Prompt.ask(
        "Default board ID (optional)",
        default=str(get_nested(existing, "default_board_id", "") or ""),
        console=console,
    )

    import httpx

    try:
        resp = httpx.get(
            f"https://api.trello.com/1/members/me?key={api_key.strip()}&token={token.strip()}",
            timeout=10,
        )
        if resp.status_code == 401:
            console.print("[red]Invalid API key or token.[/red]")
            return
        if resp.status_code != 200:
            console.print(f"[red]Trello API error: {resp.status_code}[/red]")
            return
    except httpx.ConnectError:
        console.print("[red]Cannot reach Trello API — check network.[/red]")
        return
    except httpx.TimeoutException:
        console.print("[red]Trello API timeout.[/red]")
        return

    values: dict[str, Any] = {
        "api_key": api_key.strip(),
        "token": token.strip(),
        "enabled": True,
        "auto_sync": auto_sync,
    }
    if default_board_id.strip():
        values["default_board_id"] = default_board_id.strip()

    _atomic_write(
        config_path,
        yaml.dump(values, default_flow_style=False, sort_keys=False),
    )
    console.print(f"[green]Trello configured — wrote {config_path}[/green]")


def _setup_jira_config(console: Console) -> None:
    """Prompt for Jira config in Rich (--no-tui path)."""
    config_path = Path.home() / ".claude" / "jira.yaml"
    try:
        existing = load_existing_yaml(config_path)
    except ConfigLoadError as exc:
        console.print(f"[red]Failed to load {config_path}: {exc.original}[/red]")
        return

    console.print("\n[bold]Jira Configuration[/bold]")

    enabled = Confirm.ask(
        "Enable Jira sync?",
        default=bool(get_nested(existing, "enabled", False)),
        console=console,
    )
    if not enabled:
        console.print("[dim]Skipping Jira configuration.[/dim]")
        return

    auto_sync = Confirm.ask(
        "Enable auto-sync?",
        default=bool(get_nested(existing, "auto_sync", True)),
        console=console,
    )

    base_url = Prompt.ask(
        "Jira base URL (e.g. https://yourcompany.atlassian.net)",
        default=str(get_nested(existing, "base_url", "") or ""),
        console=console,
    )
    default_user = Prompt.ask(
        "Username / email",
        default=str(get_nested(existing, "default_user", "") or ""),
        console=console,
    )

    existing_pat = str(get_nested(existing, "personal_access_token", "") or "")
    pat_input = Prompt.ask(
        "Personal access token",
        password=True,
        default=_masked_default(existing_pat),
        console=console,
    )
    personal_access_token = (
        existing_pat
        if pat_input == _masked_default(existing_pat) and existing_pat
        else pat_input
    )

    default_project = Prompt.ask(
        "Default project key (e.g. PROJ)",
        default=str(get_nested(existing, "default_project", "") or ""),
        console=console,
    )

    base_url = base_url.strip().rstrip("/")
    if not base_url:
        console.print("[red]Base URL is required.[/red]")
        return
    if not personal_access_token.strip():
        console.print("[red]Personal access token is required.[/red]")
        return

    import httpx

    try:
        resp = httpx.get(
            f"{base_url}/rest/api/3/myself",
            headers={"Authorization": f"Bearer {personal_access_token.strip()}"},
            timeout=10,
        )
        if resp.status_code == 401:
            console.print("[red]Invalid personal access token.[/red]")
            return
        if resp.status_code != 200:
            console.print(f"[red]Jira API error: {resp.status_code}[/red]")
            return
    except httpx.ConnectError:
        console.print(f"[red]Cannot reach {base_url} — check URL and network.[/red]")
        return
    except httpx.TimeoutException:
        console.print("[red]Jira API timeout.[/red]")
        return

    values: dict[str, Any] = {
        "base_url": base_url,
        "personal_access_token": personal_access_token.strip(),
        "enabled": True,
        "auto_sync": auto_sync,
    }
    if default_user.strip():
        values["default_user"] = default_user.strip()
    if default_project.strip():
        values["default_project"] = default_project.strip()

    _atomic_write(
        config_path,
        yaml.dump(values, default_flow_style=False, sort_keys=False),
    )
    console.print(f"[green]Jira configured — wrote {config_path}[/green]")


def run_wizard(selected_plugins: list[str], skip: bool = False) -> None:
    """Run the post-install setup wizard.

    Args:
        selected_plugins: List of plugin names that were installed.
        skip: If True, skip all prompts and use defaults / keep existing.
    """
    console = Console()

    if skip:
        console.print("[dim]Skipping setup wizard (--skip-wizard)[/dim]")
        return

    console.print("\n[bold]Post-install Setup Wizard[/bold]")
    console.print("Configure your plugins. Press Enter to accept defaults.\n")

    proj_plugins = {"proj", "hooks", "sandbox", "todoist", "trello", "jira"}
    if proj_plugins & set(selected_plugins):
        _setup_proj_yaml(console, selected_plugins)

    if "worktree" in selected_plugins:
        _setup_worktree_yaml(console)

    if "todoist" in selected_plugins:
        _setup_todoist_config(console)
    if "trello" in selected_plugins:
        _setup_trello_config(console)
    if "jira" in selected_plugins:
        _setup_jira_config(console)

    cache_dir = Path.home() / ".claude" / "plugins" / "cache" / "claude-project-manager"
    plugin_dirs: list[Path] = []
    for name in selected_plugins:
        resolved = _resolve_plugin_dir(cache_dir, name)
        if resolved is not None:
            plugin_dirs.append(resolved)
    if plugin_dirs:
        _hooks_diff_prompt(plugin_dirs, console=console)

    ensure_managed_section(Path.home() / ".claude" / "CLAUDE.md")

    console.print("\n[green]Setup wizard complete.[/green]")
