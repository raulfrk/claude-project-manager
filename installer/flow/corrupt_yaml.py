# installer/flow/corrupt_yaml.py
"""Rich-based replacement for Textual CorruptYamlScreen.

Displays each corrupt yaml file with its bucket, path, and parse
exception, then prompts y/n to continue with defaults.
"""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.panel import Panel

from installer.flow.yn import ask_yn


def show_corrupt_yaml_and_confirm(
    errors: dict[str, Exception], console: Console
) -> bool:
    """Render each corrupt-yaml bucket + prompt to continue with defaults.

    Short-circuits with ``True`` when ``errors`` is empty (nothing to show).
    """
    if not errors:
        return True

    console.print(
        Panel(
            "[bold red]⚠ Corrupt Configuration File(s)[/bold red]\n\n"
            "The following ~/.claude/*.yaml files could not be parsed. "
            "You can continue with defaults (values from the affected files "
            "will NOT be preserved) or cancel to fix them manually.",
            border_style="red",
        )
    )

    for bucket, exc in errors.items():
        path = Path.home() / ".claude" / f"{bucket}.yaml"
        original = getattr(exc, "original", exc)
        body = f"[bold]{bucket}.yaml[/bold]\n{path}\nReason: {original}"
        console.print(Panel(body, border_style="yellow"))

    return ask_yn("Continue with defaults?", default=False, console=console)
