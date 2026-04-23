"""List endpoint contracts for the Trello API."""

from __future__ import annotations

from tests.contracts import contract as _c

GET_LISTS = _c("GET", "/1/boards/{boardId}/lists")
GET_LIST = _c("GET", "/1/lists/{listId}")
CREATE_LIST = _c("POST", "/1/lists")
UPDATE_LIST = _c("PUT", "/1/lists/{listId}")
