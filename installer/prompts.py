"""Rich-only prompt helpers for the installer wizard.

These helpers add range validation, choice coercion, and piped-stdin
(EOFError) tolerance on top of Rich's Prompt.ask / IntPrompt.ask. They
are used ONLY from installer/wizard.py (the Rich CLI path); the Textual
TUI path handles validation via widget reactive validators.
"""

from __future__ import annotations

import sys
from typing import Sequence

from rich.console import Console
from rich.prompt import IntPrompt, Prompt


def int_in_range(
    prompt: str,
    default: int,
    low: int,
    high: int,
    console: Console,
) -> int:
    """Prompt for an int in [low, high]. Falls through to default on 3 failures or EOF.

    - If low > high, raises ValueError (programmer error).
    - If default is outside [low, high], the default is clamped into range
      before display.
    - On piped stdin (EOFError), returns default without warning.
    - On invalid input (not an int, or out of range), prints a Rich warning
      to stderr and re-prompts. After 3 failed attempts, returns default
      with a final stderr warning.
    """
    if low > high:
        raise ValueError(f"int_in_range: low={low} > high={high}")
    clamped_default = max(low, min(high, default))
    for attempt in range(3):
        try:
            value = IntPrompt.ask(prompt, default=clamped_default, console=console)
        except EOFError:
            return clamped_default
        if low <= value <= high:
            return value
        console.print(
            f"[yellow]Value must be between {low} and {high}. Got {value}. "
            f"({2 - attempt} attempt(s) left)[/yellow]",
            file=sys.stderr,
        )
    console.print(
        f"[yellow]3 invalid attempts — falling back to default {clamped_default}.[/yellow]",
        file=sys.stderr,
    )
    return clamped_default


def prompt_choice(
    prompt: str,
    default: str,
    choices: Sequence[str],
    console: Console,
) -> str:
    """Prompt for one of choices with a default. Coerces invalid default to choices[0].

    - If default is not in choices, prints a Rich warning and coerces to
      choices[0] before display.
    - On piped stdin (EOFError), returns the (possibly coerced) default.
    - Uses Rich's Prompt.ask with choices= to get built-in validation UI.
    """
    if not choices:
        raise ValueError("prompt_choice: choices must not be empty")
    effective_default = default
    if default not in choices:
        console.print(
            f"[yellow]Existing value '{default}' is not one of "
            f"{list(choices)} — coercing to '{choices[0]}'.[/yellow]",
            file=sys.stderr,
        )
        effective_default = choices[0]
    try:
        return Prompt.ask(
            prompt,
            default=effective_default,
            choices=list(choices),
            console=console,
        )
    except EOFError:
        return effective_default
