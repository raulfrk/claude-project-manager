"""Forgiving yes/no confirm prompt.

Rich's built-in ``Confirm`` only accepts exactly ``y`` or ``n`` (case-
sensitive on the prompt, lowercase-compared on the response). Typing
``yes`` gets rejected with ``Please enter Y or N``, which is unfriendly.

``ask_yn`` accepts the full set {y, yes, n, no} case-insensitively and
returns a bool. ``install_confirm_patch()`` widens Rich's own
``Confirm`` class in-place so existing ``Confirm.ask`` call sites
throughout the installer pick up the same behavior without per-site
edits.
"""

from __future__ import annotations

from rich.console import Console
from rich.prompt import Confirm, InvalidResponse, PromptBase


class _YesNoPrompt(PromptBase[bool]):
    response_type = bool
    validate_error_message = "[prompt.invalid]Please enter y, yes, n, or no"
    # Displayed set stays [y/n] — process_response widens the accepted set
    # without bloating the prompt.
    choices = ["y", "n"]

    def render_default(self, default):  # type: ignore[override]
        from rich.text import Text

        return Text("(y)" if default else "(n)", style="prompt.default")

    def process_response(self, value: str) -> bool:  # type: ignore[override]
        v = value.strip().lower()
        if v in ("y", "yes"):
            return True
        if v in ("n", "no"):
            return False
        raise InvalidResponse(self.validate_error_message)


def ask_yn(prompt: str, *, default: bool, console: Console) -> bool:
    """Prompt user for yes/no. Returns True for yes, False for no."""
    return _YesNoPrompt.ask(prompt, default=default, console=console)


_patched = False


def install_confirm_patch() -> None:
    """Widen ``rich.prompt.Confirm`` to accept yes/y/no/n case-insensitively.

    Idempotent. Safe to call multiple times — the second call is a no-op.
    """
    global _patched
    if _patched:
        return

    def _process(self: Confirm, value: str) -> bool:
        v = value.strip().lower()
        if v in ("y", "yes"):
            return True
        if v in ("n", "no"):
            return False
        raise InvalidResponse(self.validate_error_message)

    # Keep choices=["y","n"] so the rendered prompt stays "[y/n]" — we widen
    # the accepted set by replacing process_response entirely (bypasses the
    # base-class check_choice call).
    Confirm.validate_error_message = "[prompt.invalid]Please enter y, yes, n, or no"
    Confirm.process_response = _process  # type: ignore[assignment]

    _patched = True
