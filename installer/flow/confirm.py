"""Rich-based replacement for Textual ConfirmScreen.

Shows a titled panel + message, prompts y/n to confirm, then (if confirmed)
prompts y/n per option toggle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt


Variant = Literal["primary", "warning", "error"]

_VARIANT_STYLE: dict[Variant, str] = {
    "primary": "cyan",
    "warning": "yellow",
    "error": "red",
}


@dataclass
class ConfirmOption:
    key: str
    label: str
    default: bool = False


@dataclass
class ConfirmResult:
    confirmed: bool
    options: dict[str, bool] = field(default_factory=dict)


def confirm_with_options(
    title: str,
    message: str,
    options: list[ConfirmOption],
    console: Console,
    variant: Variant = "primary",
    confirm_label: str = "Confirm",
    cancel_label: str = "Cancel",
) -> ConfirmResult:
    """Display title+message panel, prompt for y/n confirm, then per-option y/n.

    Cancel short-circuits — option prompts do not fire.
    """
    border_style = _VARIANT_STYLE.get(variant, "cyan")
    console.print(Panel(message, title=title, border_style=border_style))

    proceed = Prompt.ask(
        f"{confirm_label}?",
        choices=["y", "n"],
        default="y",
        console=console,
    )
    if proceed != "y":
        return ConfirmResult(confirmed=False, options={})

    option_values: dict[str, bool] = {}
    for opt in options:
        default = "y" if opt.default else "n"
        ans = Prompt.ask(
            opt.label,
            choices=["y", "n"],
            default=default,
            console=console,
        )
        option_values[opt.key] = ans == "y"

    return ConfirmResult(confirmed=True, options=option_values)
