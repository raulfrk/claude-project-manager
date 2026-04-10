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

from installer.claudemd import ensure_managed_section
from installer.hooks_diff import apply_diffs, compute_hooks_diff

# Default config values
_DEFAULT_TRACKING_DIR = "~/projects/tracking"
_DEFAULT_PROJECTS_BASE = "~/projects"
_DEFAULT_WORKTREE_DIR = "~/worktrees"


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


def _yaml_line(key: str, value: str | bool) -> str:
    """Format a single YAML key-value line."""
    if isinstance(value, bool):
        return f"{key}: {'true' if value else 'false'}\n"
    return f"{key}: {value}\n"


def _setup_proj_yaml(console: Console, selected_plugins: list[str]) -> None:
    """Prompt for proj.yaml configuration and write it."""
    proj_yaml = Path.home() / ".claude" / "proj.yaml"

    # Check for existing config
    if proj_yaml.exists():
        try:
            content = proj_yaml.read_text(encoding="utf-8").strip()
            if content and Confirm.ask(
                f"[bold]{proj_yaml}[/bold] already exists. Keep existing config?",
                default=True,
                console=console,
            ):
                console.print("[dim]Keeping existing proj.yaml[/dim]")
                return
        except OSError:
            pass

    console.print("\n[bold]proj.yaml configuration[/bold]")

    tracking_dir = Prompt.ask(
        "Tracking directory",
        default=_DEFAULT_TRACKING_DIR,
        console=console,
    )

    projects_base = Prompt.ask(
        "Projects base directory",
        default=_DEFAULT_PROJECTS_BASE,
        console=console,
    )

    sandbox_integration = Confirm.ask(
        "Enable sandbox integration?",
        default=True,
        console=console,
    )

    zoxide_integration = Confirm.ask(
        "Enable zoxide integration?",
        default=False,
        console=console,
    )

    # Integration-specific prompts (conditional on selected plugins)
    todoist_enabled = False
    todoist_auto_sync = True
    if "todoist" in selected_plugins:
        todoist_enabled = Confirm.ask(
            "Enable Todoist sync?",
            default=False,
            console=console,
        )
        if todoist_enabled:
            todoist_auto_sync = Confirm.ask(
                "Enable Todoist auto sync?",
                default=True,
                console=console,
            )

    trello_enabled = False
    trello_auto_sync = True
    trello_board_id = ""
    if "trello" in selected_plugins:
        trello_enabled = Confirm.ask(
            "Enable Trello sync?",
            default=False,
            console=console,
        )
        if trello_enabled:
            trello_auto_sync = Confirm.ask(
                "Enable Trello auto sync?",
                default=True,
                console=console,
            )
            trello_board_id = Prompt.ask(
                "Trello board ID",
                default="",
                console=console,
            )

    jira_enabled = False
    jira_auto_sync = True
    jira_default_user = ""
    if "jira" in selected_plugins:
        jira_enabled = Confirm.ask(
            "Enable Jira sync?",
            default=False,
            console=console,
        )
        if jira_enabled:
            jira_auto_sync = Confirm.ask(
                "Enable Jira auto sync?",
                default=True,
                console=console,
            )
            jira_default_user = Prompt.ask(
                "Jira default user",
                default="",
                console=console,
            )

    # Build YAML content
    lines = [
        _yaml_line("version", "1"),
        _yaml_line("tracking_dir", tracking_dir),
        _yaml_line("projects_base_dir", projects_base),
        _yaml_line("sandbox_integration", sandbox_integration),
        _yaml_line("zoxide_integration", zoxide_integration),
    ]

    # Build nested sync config for enabled integrations
    if todoist_enabled or trello_enabled:
        lines.append("sync:\n")
        if todoist_enabled:
            lines.append("  todoist:\n")
            lines.append("    enabled: true\n")
            lines.append(f"    auto_sync: {'true' if todoist_auto_sync else 'false'}\n")
        if trello_enabled:
            lines.append("  trello:\n")
            lines.append("    enabled: true\n")
            lines.append(f"    auto_sync: {'true' if trello_auto_sync else 'false'}\n")
            if trello_board_id:
                lines.append(f"    default_board_id: {trello_board_id}\n")

    # Jira is top-level (not under sync:)
    if jira_enabled:
        lines.append("jira:\n")
        lines.append("  enabled: true\n")
        lines.append(f"  auto_sync: {'true' if jira_auto_sync else 'false'}\n")
        if jira_default_user:
            lines.append(f"  default_user: {jira_default_user}\n")

    _atomic_write(proj_yaml, "".join(lines))
    console.print(f"[green]Wrote {proj_yaml}[/green]")


def _setup_worktree_yaml(console: Console) -> None:
    """Prompt for worktree.yaml configuration and write it."""
    worktree_yaml = Path.home() / ".claude" / "worktree.yaml"

    # Check for existing config
    if worktree_yaml.exists():
        try:
            content = worktree_yaml.read_text(encoding="utf-8").strip()
            if content and Confirm.ask(
                f"[bold]{worktree_yaml}[/bold] already exists. Keep existing config?",
                default=True,
                console=console,
            ):
                console.print("[dim]Keeping existing worktree.yaml[/dim]")
                return
        except OSError:
            pass

    console.print("\n[bold]worktree.yaml configuration[/bold]")

    default_dir = Prompt.ask(
        "Default worktree directory",
        default=_DEFAULT_WORKTREE_DIR,
        console=console,
    )

    lines = [
        _yaml_line("version", "1"),
        _yaml_line("default_worktree_dir", default_dir),
    ]

    _atomic_write(worktree_yaml, "".join(lines))
    console.print(f"[green]Wrote {worktree_yaml}[/green]")


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
        # Show status badge
        badge = badge_map.get(diff.status, diff.status)
        console.print(f"  {badge}  [bold]{diff.hook_id}[/bold]")
        # Show unified diff
        if diff.unified_diff:
            console.print(diff.unified_diff)
        # Prompt — default apply for new/changed, skip for removed
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


def _read_yaml(path: Path) -> dict[str, Any]:
    """Read a YAML file and return its contents as a dict, or {} if missing/invalid."""
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, OSError, yaml.YAMLError):
        return {}


def _setup_todoist_config(console: Console) -> None:
    """Prompt for Todoist config in Rich (--no-tui path)."""
    config_path = Path.home() / ".claude" / "todoist.yaml"
    existing = _read_yaml(config_path)

    console.print("\n[bold]Todoist Configuration[/bold]")

    enabled = Confirm.ask(
        "Enable Todoist sync?",
        default=bool(existing.get("enabled", False)),
        console=console,
    )
    if not enabled:
        console.print("[dim]Skipping Todoist configuration.[/dim]")
        return

    auto_sync = Confirm.ask(
        "Enable auto-sync?",
        default=bool(existing.get("auto_sync", True)),
        console=console,
    )

    api_token = Prompt.ask(
        "Todoist API token",
        password=True,
        default=existing.get("api_token", ""),
        console=console,
    )
    if not api_token.strip():
        console.print("[red]API token is required.[/red]")
        return

    # Validate token against Todoist REST API
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
    existing = _read_yaml(config_path)

    console.print("\n[bold]Trello Configuration[/bold]")

    enabled = Confirm.ask(
        "Enable Trello sync?",
        default=bool(existing.get("enabled", False)),
        console=console,
    )
    if not enabled:
        console.print("[dim]Skipping Trello configuration.[/dim]")
        return

    auto_sync = Confirm.ask(
        "Enable auto-sync?",
        default=bool(existing.get("auto_sync", True)),
        console=console,
    )

    api_key = Prompt.ask(
        "Trello API key",
        password=True,
        default=existing.get("api_key", ""),
        console=console,
    )
    token = Prompt.ask(
        "Trello token",
        password=True,
        default=existing.get("token", ""),
        console=console,
    )
    if not api_key.strip() or not token.strip():
        console.print("[red]API key and token are both required.[/red]")
        return

    default_board_id = Prompt.ask(
        "Default board ID (optional)",
        default=existing.get("default_board_id", ""),
        console=console,
    )

    # Validate credentials against Trello API
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
    existing = _read_yaml(config_path)

    console.print("\n[bold]Jira Configuration[/bold]")

    enabled = Confirm.ask(
        "Enable Jira sync?",
        default=bool(existing.get("enabled", False)),
        console=console,
    )
    if not enabled:
        console.print("[dim]Skipping Jira configuration.[/dim]")
        return

    auto_sync = Confirm.ask(
        "Enable auto-sync?",
        default=bool(existing.get("auto_sync", True)),
        console=console,
    )

    base_url = Prompt.ask(
        "Jira base URL (e.g. https://yourcompany.atlassian.net)",
        default=str(existing.get("base_url", "")),
        console=console,
    )
    default_user = Prompt.ask(
        "Username / email",
        default=str(existing.get("default_user", "")),
        console=console,
    )
    personal_access_token = Prompt.ask(
        "Personal access token",
        password=True,
        default=str(existing.get("personal_access_token", "")),
        console=console,
    )
    default_project = Prompt.ask(
        "Default project key (e.g. PROJ)",
        default=str(existing.get("default_project", "")),
        console=console,
    )

    base_url = base_url.strip().rstrip("/")
    if not base_url:
        console.print("[red]Base URL is required.[/red]")
        return
    if not personal_access_token.strip():
        console.print("[red]Personal access token is required.[/red]")
        return

    # Validate credentials against Jira API
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

    # proj.yaml is needed by proj, hooks, sandbox, and most other plugins
    proj_plugins = {"proj", "hooks", "sandbox", "todoist", "trello", "jira"}
    if proj_plugins & set(selected_plugins):
        _setup_proj_yaml(console, selected_plugins)

    # worktree.yaml only if worktree was selected
    if "worktree" in selected_plugins:
        _setup_worktree_yaml(console)

    # Integration config (API tokens with validation)
    if "todoist" in selected_plugins:
        _setup_todoist_config(console)
    if "trello" in selected_plugins:
        _setup_trello_config(console)
    if "jira" in selected_plugins:
        _setup_jira_config(console)

    # Hooks diff prompt — resolve installed plugin dirs from cache
    cache_dir = Path.home() / ".claude" / "plugins" / "cache" / "claude-project-manager"
    plugin_dirs: list[Path] = []
    for name in selected_plugins:
        resolved = _resolve_plugin_dir(cache_dir, name)
        if resolved is not None:
            plugin_dirs.append(resolved)
    if plugin_dirs:
        _hooks_diff_prompt(plugin_dirs, console=console)

    # Ensure managed section in global CLAUDE.md
    ensure_managed_section(Path.home() / ".claude" / "CLAUDE.md")

    console.print("\n[green]Setup wizard complete.[/green]")
