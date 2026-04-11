"""Detection logic for existing installations."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table


@dataclass
class InstallState:
    """Snapshot of an existing claude-project-manager installation."""

    proj_yaml: Path | None = None
    worktree_yaml: Path | None = None
    settings_json: Path | None = None
    marketplace_dir: Path | None = None
    cache_dir: Path | None = None
    installed_plugins: list[str] = field(default_factory=list)
    mcp_entries: list[str] = field(default_factory=list)


def _safe_stat(path: Path) -> datetime | None:
    """Return mtime as datetime or None if inaccessible."""
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except (OSError, PermissionError):
        return None


def _parse_mcp_entries(settings_path: Path) -> list[str]:
    """Extract plugin_*_* MCP server entries from settings.json."""
    try:
        data = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, PermissionError, json.JSONDecodeError):
        return []

    entries: list[str] = []
    # Look in mcpServers for plugin_*_* keys
    mcp_servers = data.get("mcpServers", {})
    if isinstance(mcp_servers, dict):
        for key in mcp_servers:
            if key.startswith("plugin_") and key.count("_") >= 2:
                entries.append(key)
    return sorted(entries)


# NOTE: on-disk inventory, NOT authoritative. Use plugin_cli.get_installed_plugins() for install/reinstall decisions.
def _parse_installed_plugins(cache_dir: Path) -> list[str]:
    """List plugin names from the cache directory."""
    if not cache_dir.is_dir():
        return []
    try:
        return sorted(
            d.name
            for d in cache_dir.iterdir()
            if d.is_dir() and not d.name.startswith(".")
        )
    except (OSError, PermissionError):
        return []


def _validate_yaml(path: Path) -> bool:
    """Check if a YAML file exists and is non-empty."""
    try:
        content = path.read_text(encoding="utf-8").strip()
        return len(content) > 0
    except (OSError, PermissionError):
        return False


def detect_existing() -> InstallState:
    """Detect an existing claude-project-manager installation.

    Checks standard locations under ~/.claude/ for config files,
    marketplace directory, cache directory, and MCP server entries.
    """
    claude_dir = Path.home() / ".claude"
    state = InstallState()

    # Config files
    proj_yaml = claude_dir / "proj.yaml"
    if proj_yaml.exists():
        state.proj_yaml = proj_yaml

    worktree_yaml = claude_dir / "worktree.yaml"
    if worktree_yaml.exists():
        state.worktree_yaml = worktree_yaml

    # Settings JSON
    settings_json = claude_dir / "settings.json"
    if settings_json.exists():
        state.settings_json = settings_json
        state.mcp_entries = _parse_mcp_entries(settings_json)

    # Marketplace directory
    marketplace_dir = claude_dir / "plugins" / "marketplaces" / "claude-project-manager"
    if marketplace_dir.exists():
        state.marketplace_dir = marketplace_dir

    # Cache directory
    cache_dir = claude_dir / "plugins" / "cache" / "claude-project-manager"
    if cache_dir.exists():
        state.cache_dir = cache_dir
        state.installed_plugins = _parse_installed_plugins(cache_dir)

    return state


def is_clean(state: InstallState) -> bool:
    """Return True if no existing installation was detected."""
    return (
        state.proj_yaml is None
        and state.worktree_yaml is None
        and state.marketplace_dir is None
        and state.cache_dir is None
        and not state.mcp_entries
    )


def display_detection(state: InstallState, console: Console) -> None:
    """Display a Rich table summarizing the detected installation state."""
    table = Table(title="Existing Installation", show_lines=True)
    table.add_column("Component", style="bold")
    table.add_column("Path")
    table.add_column("Status")
    table.add_column("Last Modified")

    items: list[tuple[str, Path | None]] = [
        ("proj.yaml", state.proj_yaml),
        ("worktree.yaml", state.worktree_yaml),
        ("settings.json", state.settings_json),
        ("Marketplace dir", state.marketplace_dir),
        ("Cache dir", state.cache_dir),
    ]

    for label, path in items:
        if path is None:
            table.add_row(label, "-", "[dim]not found[/dim]", "-")
        else:
            mtime = _safe_stat(path)
            mtime_str = mtime.strftime("%Y-%m-%d %H:%M:%S") if mtime else "unknown"
            valid = True
            if path.suffix in (".yaml", ".yml"):
                valid = _validate_yaml(path)
            status = (
                "[green]found[/green]" if valid else "[yellow]empty/malformed[/yellow]"
            )
            table.add_row(label, str(path), status, mtime_str)

    console.print(table)

    if state.installed_plugins:
        console.print(
            f"\n[bold]Installed plugins:[/bold] {', '.join(state.installed_plugins)}"
        )

    if state.mcp_entries:
        console.print(
            f"[bold]MCP server entries:[/bold] {', '.join(state.mcp_entries)}"
        )


def prompt_action(state: InstallState) -> Literal["reinitialize", "keep", "abort"]:
    """Prompt the user to choose how to handle the existing installation.

    Returns one of:
        "reinitialize" - back up and start fresh
        "keep"         - keep existing config and update/add plugins
        "abort"        - cancel the installation
    """
    console = Console()
    console.print("\n[bold]An existing installation was detected.[/bold]")
    console.print(
        "  1) [bold]Reinitialize[/bold] - back up current state and start fresh"
    )
    console.print("  2) [bold]Keep[/bold] - keep existing config, update/add plugins")
    console.print("  3) [bold]Abort[/bold] - cancel installation")

    choice = Prompt.ask("Select an option", choices=["1", "2", "3"], default="2")

    mapping: dict[str, Literal["reinitialize", "keep", "abort"]] = {
        "1": "reinitialize",
        "2": "keep",
        "3": "abort",
    }
    return mapping[choice]


def create_backup(state: InstallState) -> Path:
    """Create a backup of the current installation state.

    Copies all detected files/directories to ~/.claude/backups/cpm-<timestamp>/.
    Returns the backup directory path.

    Raises:
        OSError: If the backup directory cannot be created or files cannot be copied.
    """
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    backup_dir = Path.home() / ".claude" / "backups" / f"cpm-{timestamp}"
    backup_dir.mkdir(parents=True, exist_ok=True)

    paths_to_back_up: list[Path | None] = [
        state.proj_yaml,
        state.worktree_yaml,
        state.settings_json,
    ]

    for path in paths_to_back_up:
        if path is not None and path.exists():
            try:
                dest = backup_dir / path.name
                shutil.copy2(path, dest)
            except (OSError, PermissionError) as exc:
                Console().print(
                    f"[yellow]Warning: could not back up {path}: {exc}[/yellow]"
                )

    dirs_to_back_up: list[tuple[str, Path | None]] = [
        ("marketplace", state.marketplace_dir),
        ("cache", state.cache_dir),
    ]

    for label, dir_path in dirs_to_back_up:
        if dir_path is not None and dir_path.exists():
            try:
                dest = backup_dir / label
                shutil.copytree(dir_path, dest, dirs_exist_ok=True)
            except (OSError, PermissionError) as exc:
                Console().print(
                    f"[yellow]Warning: could not back up {label} dir: {exc}[/yellow]"
                )

    return backup_dir
