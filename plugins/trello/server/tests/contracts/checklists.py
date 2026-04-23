"""Checklist endpoint contracts for the Trello API."""

from __future__ import annotations

from tests.contracts import contract as _c

CREATE_CHECKLIST = _c("POST", "/1/checklists")
ADD_CHECKLIST_ITEM = _c("POST", "/1/checklists/{checklistId}/checkItems")
UPDATE_CHECKLIST_ITEM = _c("PUT", "/1/cards/{cardId}/checklist/{checklistId}/checkItem/{itemId}")
DELETE_CHECKLIST = _c("DELETE", "/1/checklists/{checklistId}")
RENAME_CHECKLIST_ITEM = _c("PUT", "/1/cards/{cardId}/checkItem/{itemId}")
DELETE_CHECKLIST_ITEM = _c("DELETE", "/1/cards/{cardId}/checkItem/{itemId}")
RENAME_CHECKLIST = _c("PUT", "/1/checklists/{checklistId}")
