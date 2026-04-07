"""Post-install setup wizard."""

from __future__ import annotations

import contextlib
import os
import tempfile
from pathlib import Path

from rich.console import Console
from rich.prompt import Confirm, Prompt

# Default config values
_DEFAULT_TRACKING_DIR = "~/projects/tracking"
_DEFAULT_PROJECTS_BASE = "~/projects"
_DEFAULT_WORKTREE_DIR = "~/worktrees"


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


def _setup_proj_yaml(console: Console) -> None:
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

    # Build YAML content
    lines = [
        _yaml_line("version", "1"),
        _yaml_line("tracking_dir", tracking_dir),
        _yaml_line("projects_base_dir", projects_base),
        _yaml_line("sandbox_integration", sandbox_integration),
        _yaml_line("zoxide_integration", zoxide_integration),
    ]

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
        _setup_proj_yaml(console)

    # worktree.yaml only if worktree was selected
    if "worktree" in selected_plugins:
        _setup_worktree_yaml(console)

    console.print("\n[green]Setup wizard complete.[/green]")
