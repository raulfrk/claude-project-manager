"""Board endpoint contracts for the Trello API."""

from __future__ import annotations

from tests.contracts import contract as _c

LIST_BOARDS = _c("GET", "/1/members/me/boards")
GET_BOARD = _c("GET", "/1/boards/{boardId}")
UPDATE_BOARD = _c("PUT", "/1/boards/{boardId}")
GET_BOARD_MEMBERS = _c("GET", "/1/boards/{boardId}/members")
