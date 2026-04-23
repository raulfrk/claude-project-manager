"""Jira API contract definitions for endpoint and error testing.

Endpoint contracts are built from the vendored OpenAPI spec at
``openapi/jira-dc-v2.json`` (hand-authored since Atlassian publishes no
OpenAPI for Jira Server/DC — see the design doc).
"""

from __future__ import annotations

from pathlib import Path

_SPEC_PATH = Path(__file__).parent / "openapi" / "jira-dc-v2.json"
