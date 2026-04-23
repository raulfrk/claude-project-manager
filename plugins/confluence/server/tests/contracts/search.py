"""Confluence search endpoint contracts."""

from __future__ import annotations

from tests.contracts import cloud, server

SEARCH_CLOUD = cloud("GET", "/wiki/rest/api/search")
SEARCH_SERVER = server("GET", "/rest/api/search")
