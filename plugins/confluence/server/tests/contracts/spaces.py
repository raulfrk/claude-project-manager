"""Confluence space endpoint contracts."""

from __future__ import annotations

from tests.contracts import cloud, server

LIST_SPACES_CLOUD = cloud("GET", "/wiki/rest/api/space")
LIST_SPACES_SERVER = server("GET", "/rest/api/space")
