# installer/flow/config_diff.py
"""Rich-based replacement for Textual ConfigDiffScreen.

Renders a unified yaml diff with Rich Syntax highlighting + prompts y/n
to apply. Mirrors the Textual screen's bool return value.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax


def review_config_diff(service_name: str, diff_text: str, console: Console) -> bool:
    """Show diff + prompt apply/cancel.

    Short-circuits with ``True`` when ``diff_text`` is empty (nothing to apply anyway).
    """
    if not diff_text.strip():
        return True

    console.print(f"[bold]Configuration Changes — {service_name}[/bold]")
    syntax = Syntax(diff_text, "diff", theme="ansi_dark", line_numbers=False)
    console.print(Panel(syntax, border_style="cyan"))

    proceed = Prompt.ask("Apply?", choices=["y", "n"], default="y", console=console)
    return proceed == "y"
