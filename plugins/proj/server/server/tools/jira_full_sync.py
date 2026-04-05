"""Jira full sync helpers — socket-based inter-plugin communication."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import httpx

from server.lib.models import JsonValue

log = logging.getLogger(__name__)


def _fetch_jira_issues(project_key: str | None = None, max_results: int = 200) -> tuple[list[dict[str, JsonValue]], int]:
    """Fetch issues from Jira via socket, unwrap envelope, return (issues, total)."""
    params: dict[str, JsonValue] = {"max_results": max_results}
    if project_key:
        params["project_key"] = project_key
    result = _call_jira_tool("jira_get_user_issues", params)
    # Unwrap {"issues": [...], "total": N} envelope
    issues: list[dict[str, JsonValue]]
    total: int
    if isinstance(result, dict) and "issues" in result:
        issues_raw = result["issues"]
        issues = [i for i in issues_raw if isinstance(i, dict)] if isinstance(issues_raw, list) else []
        total_raw = result.get("total", len(issues))
        total = int(total_raw) if isinstance(total_raw, (int, float)) else len(issues)
    elif isinstance(result, list):
        issues = [i for i in result if isinstance(i, dict)]
        total = len(issues)
    else:
        issues = []
        total = 0
    if total > len(issues):
        log.warning(
            "Jira pagination: fetched %d of %d total issues. "
            "Use max_results parameter to fetch more.",
            len(issues), total,
        )
    return issues, total


def _resolve_jira_socket() -> str:
    """Read Jira plugin socket path from registry, fall back to legacy."""
    registry_file = Path.home() / ".claude" / "sockets" / "jira"
    try:
        path = registry_file.read_text().strip()
        if path:
            return path
    except (FileNotFoundError, OSError):
        pass
    return "/tmp/claude-hooks-jira.sock"


def _call_jira_tool(tool_name: str, params: dict[str, JsonValue]) -> JsonValue:
    """Call a Jira MCP tool via inter-plugin Unix domain socket."""
    sock_path = _resolve_jira_socket()
    transport = httpx.HTTPTransport(uds=sock_path)
    with httpx.Client(transport=transport, timeout=30.0) as client:
        resp = client.post(
            "http://localhost/hook",
            json={"tool": tool_name, "params": params},
        )
        resp.raise_for_status()
        data = resp.json()
        # Check for error payloads
        if isinstance(data, dict):
            if "error" in data:
                raise RuntimeError(f"Jira tool error: {data['error']}")
            if data.get("ok") is False:
                raise RuntimeError(f"Jira transport error: {data}")
            # Unwrap {"ok": True, "result": ...} envelope
            if "result" in data:
                result = data["result"]
                # Tools return json.dumps(...) strings — parse them
                if isinstance(result, str):
                    try:
                        return json.loads(result)  # type: ignore[no-any-return]  # json.loads returns Any
                    except (json.JSONDecodeError, ValueError):
                        return result
                return result  # type: ignore[no-any-return]  # json.loads returns Any per stdlib
        return data  # type: ignore[no-any-return]  # resp.json() returns Any per httpx
