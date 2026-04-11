"""Trello label name normalization + duplicate-tiebreak helpers.

Used by the `trello-setup` sub-skill preflight. The skill reads the
normalization rules from its SKILL.md but the actual validation logic lives
here so it is unit-testable.
"""

from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass

from server.lib.models import trello_label_name_length_limit

_logger = logging.getLogger(__name__)


class LabelNameError(ValueError):
    """Raised when a configured Trello label name fails preflight validation."""


@dataclass(frozen=True)
class TrelloLabel:
    """Minimal shape of a Trello label as returned by `get_labels`."""

    id: str
    name: str
    color: str


def normalize_label_name(value: str, *, field_name: str = "proj_label_name") -> str:
    """Strip → reject-empty → reject-control-char → NFC-normalize.

    Raises LabelNameError on any rejection. Returns the normalized name.
    Logs a warning (does NOT raise) if the normalized name exceeds
    `trello_label_name_length_limit`.
    """
    # Reject control chars on the raw value, before stripping. `.strip()`
    # removes trailing `\n`/`\t`/`\r` and would mask the typo otherwise.
    for ch in value:
        if ord(ch) < 32:
            raise LabelNameError(
                f"Label name contains control characters — pick a printable name "
                f"(sync.trello.{field_name})",
            )
    stripped = value.strip()
    if stripped == "":
        raise LabelNameError(
            f"Label name is empty — set sync.trello.{field_name} in proj.yaml",
        )
    nfc = unicodedata.normalize("NFC", stripped)
    if len(nfc) > trello_label_name_length_limit:
        _logger.warning(
            "Trello label name for sync.trello.%s exceeds soft cap of %d chars "
            "(%d chars) — consider shortening",
            field_name,
            trello_label_name_length_limit,
            len(nfc),
        )
    return nfc


def match_label(
    configured_name: str,
    preferred_color: str,
    board_labels: list[TrelloLabel],
) -> TrelloLabel | None:
    """Return the matching TrelloLabel or None if no match.

    Raises LabelNameError if multiple labels match and no tiebreak resolves.

    Match rule: case-sensitive NFC-stripped name equality.
    Tiebreak rule (when multiple labels match the name):
      1. Prefer exact (name, color) match with the preferred color.
      2. Else prefer the first in board_labels order (API pagination order).
      3. Else hard error.

    The `configured_name` MUST already be normalized via normalize_label_name.
    """
    candidates: list[TrelloLabel] = []
    for lbl in board_labels:
        board_name_norm = unicodedata.normalize("NFC", lbl.name.strip())
        if board_name_norm == configured_name:
            candidates.append(lbl)
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    # Multiple candidates: tiebreak by color, then by API order.
    exact_color = [c for c in candidates if c.color == preferred_color]
    if len(exact_color) == 1:
        return exact_color[0]
    if len(exact_color) >= 2:
        # Multiple matches with the same (name, color) pair — ambiguous.
        conflicts = ", ".join(f"id={c.id} color={c.color}" for c in exact_color)
        raise LabelNameError(
            f"Multiple labels named '{configured_name}' found on board: "
            f"{conflicts}. Delete one manually, then re-run trello-setup.",
        )
    # No exact-color winner and multiple name matches: fall back to first
    # in API order (stable per get_labels call).
    return candidates[0]
