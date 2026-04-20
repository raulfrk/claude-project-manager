"""Rich-based replacement for Textual ConfirmScreen.

Shows a titled panel + message, prompts y/n to confirm, then (if confirmed)
prompts y/n per option toggle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from rich.console import Console
from rich.panel import Panel

from installer.flow.yn import ask_yn


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

    if not ask_yn(f"{confirm_label}?", default=True, console=console):
        return ConfirmResult(confirmed=False, options={})

    option_values: dict[str, bool] = {}
    for opt in options:
        option_values[opt.key] = ask_yn(opt.label, default=opt.default, console=console)

    return ConfirmResult(confirmed=True, options=option_values)
