"""Card endpoint contracts for the Trello API."""

from __future__ import annotations

from tests.contracts import contract as _c

GET_CARDS_BY_LIST = _c("GET", "/1/lists/{listId}/cards")
GET_CARD = _c("GET", "/1/cards/{cardId}")
ADD_CARD = _c("POST", "/1/cards")
UPDATE_CARD = _c("PUT", "/1/cards/{cardId}")
DELETE_CARD = _c("DELETE", "/1/cards/{cardId}")
ADD_CARD_MEMBER = _c("POST", "/1/cards/{cardId}/idMembers")
REMOVE_CARD_MEMBER = _c("DELETE", "/1/cards/{cardId}/idMembers/{memberId}")
ADD_CARD_LABEL = _c("POST", "/1/cards/{cardId}/idLabels")
REMOVE_CARD_LABEL = _c("DELETE", "/1/cards/{cardId}/idLabels/{labelId}")
GET_CARD_COMMENTS = _c("GET", "/1/cards/{cardId}/actions")
ADD_COMMENT = _c("POST", "/1/cards/{cardId}/actions/comments")
GET_CARD_ATTACHMENTS = _c("GET", "/1/cards/{cardId}/attachments")
ADD_ATTACHMENT = _c("POST", "/1/cards/{cardId}/attachments")
DELETE_ATTACHMENT = _c("DELETE", "/1/cards/{cardId}/attachments/{attachmentId}")
GET_CARD_CHECKLISTS = _c("GET", "/1/cards/{cardId}/checklists")
