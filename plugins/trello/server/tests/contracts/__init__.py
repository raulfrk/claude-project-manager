"""Trello API contract definitions.

Endpoint contracts are built from the vendored OpenAPI spec at
``openapi/trello-v1.json`` (APIs.guru community spec) merged with a local
supplement at ``openapi/trello-v1-supplement.json`` for endpoints the
community spec doesn't cover.

Path placeholders are normalised: the community spec uses ``{idBoard}``,
``{idCard}`` etc., but the plugin client sends ``{boardId}``, ``{cardId}``
— normalisation happens at load time so contract lookup uses the
plugin's form.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from test_contracts.openapi import endpoint_contract, load_merged, rename_path_placeholders

if TYPE_CHECKING:
    from test_contracts.base import EndpointContract

_DIR = Path(__file__).parent / "openapi"

# Load + merge community spec and hand-authored supplement.
# Supplement wins on path collisions (shouldn't collide in practice).
_SPEC = rename_path_placeholders(
    load_merged(_DIR / "trello-v1.json", _DIR / "trello-v1-supplement.json"),
    aliases={
        "{idBoard}": "{boardId}",
        "{idCard}": "{cardId}",
        "{idList}": "{listId}",
        "{idLabel}": "{labelId}",
        "{idMember}": "{memberId}",
        "{idChecklist}": "{checklistId}",
        # APIs.guru uses {idChecklistCurrent} for the PUT-update-checkItem path
        # — a one-off inconsistency; normalise so lookup matches our URL form.
        "{idChecklistCurrent}": "{checklistId}",
        "{idCheckItem}": "{itemId}",
        "{idAttachment}": "{attachmentId}",
        "{idAction}": "{actionId}",
    },
)


def contract(method: str, url_pattern: str, *, status: str | int = "2xx") -> EndpointContract:
    """Build a Trello endpoint contract.

    ``url_pattern`` uses the plugin's form (with ``/1/`` prefix) — that's
    what the real request URL looks like. The spec lookup strips ``/1/``
    because the community spec's ``servers`` URL already includes it.

    Trello uses query-string parameters for input on POST/PUT endpoints
    (not JSON bodies), so ``request_schema`` is suppressed — the
    community spec's ``requestBody`` definitions don't reflect the
    actual request shape.
    """
    assert url_pattern.startswith("/1/"), (
        f"trello URL patterns must start with /1/ (got {url_pattern!r})"
    )
    return endpoint_contract(
        _SPEC,
        method,
        url_pattern,
        spec_url_pattern=url_pattern.removeprefix("/1"),
        required_headers={},
        auth_style="query_params",
        status=status,
        no_request_body=True,
    )
