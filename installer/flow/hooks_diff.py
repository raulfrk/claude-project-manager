# installer/flow/hooks_diff.py
"""Rich-based replacement for Textual HooksDiffScreen.

Renders each HookDiff (new/changed/removed) in a Rich Panel with the
unified diff syntax-highlighted, then prompts apply-all / skip-all /
cancel. Return value mirrors the Textual screen: {"apply": set, "remove": set}
or None on cancel.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt
from rich.syntax import Syntax

from installer.hooks_diff import HookDiff


_STATUS_STYLE: dict[str, str] = {
    "new": "green",
    "changed": "yellow",
    "removed": "red",
}


def review_hooks_diff(
    diffs: list[HookDiff], console: Console
) -> dict[str, set[str]] | None:
    """Show diffs + prompt for apply-all / skip-all / cancel.

    Returns ``{"apply": set, "remove": set}`` (keys always present) or
    ``None`` if user cancels. Empty ``diffs`` returns empty sets with no prompt.
    """
    if not diffs:
        return {"apply": set(), "remove": set()}

    console.print("[bold]Hook Configuration Updates[/bold]")

    for diff in diffs:
        style = _STATUS_STYLE.get(diff.status, "cyan")
        header = f"[{style}]{diff.status.upper()}[/] {diff.hook_id}"
        syntax = Syntax(
            diff.unified_diff, "diff", theme="ansi_dark", line_numbers=False
        )
        console.print(Panel(syntax, title=header, border_style=style))

    choice = Prompt.ask(
        "Action",
        choices=["a", "s", "c"],
        default="a",
        console=console,
    )
    if choice == "c":
        return None

    apply_ids: set[str] = set()
    remove_ids: set[str] = set()

    if choice == "a":
        for d in diffs:
            if d.status in ("new", "changed"):
                apply_ids.add(d.hook_id)
            elif d.status == "removed":
                remove_ids.add(d.hook_id)

    return {"apply": apply_ids, "remove": remove_ids}
