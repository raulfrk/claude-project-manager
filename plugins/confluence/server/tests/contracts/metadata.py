"""Contracts for attachments + comments endpoints."""

from __future__ import annotations

from tests.contracts import cloud, server

LIST_ATTACHMENTS_CLOUD = cloud("GET", "/wiki/rest/api/content/{id}/child/attachment")
LIST_ATTACHMENTS_SERVER = server("GET", "/rest/api/content/{id}/child/attachment")
LIST_COMMENTS_CLOUD = cloud("GET", "/wiki/rest/api/content/{id}/child/comment")
LIST_COMMENTS_SERVER = server("GET", "/rest/api/content/{id}/child/comment")
