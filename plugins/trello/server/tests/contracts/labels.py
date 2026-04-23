"""Label endpoint contracts for the Trello API."""

from __future__ import annotations

from tests.contracts import contract as _c

GET_LABELS = _c("GET", "/1/boards/{boardId}/labels")
CREATE_LABEL = _c("POST", "/1/labels")
UPDATE_LABEL = _c("PUT", "/1/labels/{labelId}")
DELETE_LABEL = _c("DELETE", "/1/labels/{labelId}")
