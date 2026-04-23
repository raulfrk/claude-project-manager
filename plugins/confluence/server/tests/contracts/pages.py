"""Confluence page endpoint contracts."""

from __future__ import annotations

from tests.contracts import cloud, server

GET_PAGE_CLOUD = cloud("GET", "/wiki/rest/api/content/{id}")
GET_PAGE_SERVER = server("GET", "/rest/api/content/{id}")
GET_PAGE_BY_TITLE_CLOUD = cloud("GET", "/wiki/rest/api/content")
GET_PAGE_BY_TITLE_SERVER = server("GET", "/rest/api/content")

# Placeholders for future tests — keep aliases.
LIST_PAGES_CLOUD = GET_PAGE_BY_TITLE_CLOUD
LIST_PAGES_SERVER = GET_PAGE_BY_TITLE_SERVER

TREE_CLOUD = cloud("GET", "/wiki/rest/api/content/{id}/descendant/page")
TREE_SERVER = server("GET", "/rest/api/content/{id}/descendant/page")
