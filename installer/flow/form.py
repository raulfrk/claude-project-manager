# installer/flow/form.py
"""Shared prompt_toolkit form builder.

FieldSpec describes one input field. run_form builds a prompt_toolkit
Application (or sequential dialogs — see Fallback section) that renders
all fields with Tab-focus cycling, per-field validators, Enter-to-submit,
Escape-to-cancel.

Returns {key: value} dict on submit, None on cancel. Loops on validator
failure — re-renders with the error banner + preserved current values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from rich.console import Console


FieldKind = Literal["text", "password", "bool", "int", "select"]


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    kind: FieldKind
    default: Any = None
    choices: list[str] | None = None
    validator: Callable[[Any], str | None] | None = None
    help_text: str | None = None
    group: str | None = None


def _build_application(
    fields: list[FieldSpec],
    *,
    title: str | None = None,
    error_message: str | None = None,
) -> Any:
    """Build prompt_toolkit application (or fallback dialog loop).

    Returns an object with a `.run()` method that:
    - Returns dict[str, Any] on clean submit
    - Returns dict[str, Any] with `_form_error` + `_values` keys when validator failed
    - Returns None on cancel
    """
    # Primary: sequential shortcut dialogs. Simpler than a full Application.
    # Each field becomes one dialog. Validator runs on submit; failure short-circuits
    # with _form_error so run_form can loop.
    from prompt_toolkit.shortcuts import (
        input_dialog,
        radiolist_dialog,
        yes_no_dialog,
    )

    class _FormRunner:
        def run(self) -> Any:
            values: dict[str, Any] = {}
            for spec in fields:
                # Compose dialog text including optional help_text + any banner
                dialog_text_parts: list[str] = []
                if error_message:
                    dialog_text_parts.append(f"[Error: {error_message}]\n")
                if spec.help_text:
                    dialog_text_parts.append(spec.help_text)
                dialog_text = "\n".join(dialog_text_parts) or ""
                dialog_title = title if title else spec.label

                if spec.kind in ("text", "password"):
                    raw = input_dialog(
                        title=dialog_title,
                        text=f"{spec.label}\n{dialog_text}".strip() or spec.label,
                        default=str(spec.default or ""),
                        password=(spec.kind == "password"),
                    ).run()
                    if raw is None:
                        return None
                    values[spec.key] = raw
                elif spec.kind == "int":
                    raw = input_dialog(
                        title=dialog_title,
                        text=f"{spec.label}\n{dialog_text}".strip() or spec.label,
                        default=str(spec.default or 0),
                    ).run()
                    if raw is None:
                        return None
                    try:
                        values[spec.key] = int(raw)
                    except (TypeError, ValueError):
                        values[spec.key] = 0
                elif spec.kind == "bool":
                    raw = yes_no_dialog(
                        title=dialog_title,
                        text=f"{spec.label}\n{dialog_text}".strip() or spec.label,
                    ).run()
                    if raw is None:
                        return None
                    values[spec.key] = bool(raw)
                elif spec.kind == "select":
                    choices = spec.choices or []
                    raw = radiolist_dialog(
                        title=dialog_title,
                        text=f"{spec.label}\n{dialog_text}".strip() or spec.label,
                        values=[(c, c) for c in choices],
                        default=spec.default if spec.default in choices else None,
                    ).run()
                    if raw is None:
                        return None
                    values[spec.key] = raw
                else:
                    raise ValueError(f"Unknown FieldKind: {spec.kind}")

            # Validators pass
            for spec in fields:
                if spec.validator is None:
                    continue
                err = spec.validator(values.get(spec.key))
                if err:
                    return {"_form_error": err, "_values": values}
            return values

    return _FormRunner()


def run_form(
    fields: list[FieldSpec],
    console: Console,
    *,
    title: str | None = None,
    error_message: str | None = None,
) -> dict[str, Any] | None:
    """Render form + return {key: value} dict on submit, None on cancel.

    Loops on validator failure: re-renders with the error banner + preserved
    current values until the user passes validation or cancels.
    """
    if not fields:
        return {}

    current_error = error_message
    current_defaults: dict[str, Any] = {spec.key: spec.default for spec in fields}

    while True:
        fields_with_defaults = [
            FieldSpec(
                key=spec.key,
                label=spec.label,
                kind=spec.kind,
                default=current_defaults.get(spec.key, spec.default),
                choices=spec.choices,
                validator=spec.validator,
                help_text=spec.help_text,
                group=spec.group,
            )
            for spec in fields
        ]
        app = _build_application(
            fields_with_defaults, title=title, error_message=current_error
        )
        raw = app.run()
        if raw is None:
            return None
        if isinstance(raw, dict) and "_form_error" in raw:
            current_error = raw["_form_error"]
            current_defaults = raw["_values"]
            continue
        return raw
