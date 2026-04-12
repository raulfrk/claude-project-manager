"""CLI entrypoint for hooks (shares lib/ with MCP server, no MCP stdio needed)."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import socket
import sys
from datetime import date
from pathlib import Path

from server.lib import storage
from server.tools.context import _build_context, ctx_detect_project_name
from server.tools.digest import _deduplicate, _parse_session

logger = logging.getLogger(__name__)

_SOCKET_DIR = "/tmp"  # noqa: S108
_SOCKET_PREFIX = "claude-cpm-"
_SOCKET_REGISTRY_DIR = Path.home() / ".claude" / "sockets"


def _call_proj_socket(tool: str, params: dict) -> None:  # type: ignore[type-arg]
    """Call a tool on the proj MCP server via its Unix domain socket.

    Resolves the socket path from the registry file (~/.claude/sockets/proj).
    Falls back to globbing /tmp for PID-tagged sockets if registry is missing.
    Silently no-ops if the socket is unreachable (MCP server not yet started).
    """
    # Resolve socket path from registry
    sock_path: str | None = None
    registry_file = _SOCKET_REGISTRY_DIR / "proj"
    try:
        path = registry_file.read_text().strip()
        if path and Path(path).exists():
            sock_path = path
    except (FileNotFoundError, OSError):
        pass

    # Fallback: glob for newest PID-tagged socket
    if not sock_path:
        candidates = sorted(
            Path(_SOCKET_DIR).glob(f"{_SOCKET_PREFIX}proj-*.sock"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for candidate in candidates:
            sock_path = str(candidate)
            break

    if not sock_path:
        logger.debug("proj socket not found; skipping socket activation")
        return

    payload = json.dumps({"tool": tool, "params": params}).encode()
    request = (
        b"POST /hook HTTP/1.0\r\n"
        b"Host: localhost\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(len(payload)).encode() + b"\r\n"
        b"\r\n" + payload
    )
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(5.0)
            sock.connect(sock_path)
            sock.sendall(request)
            # Read response (ignore content, just drain to avoid broken pipe)
            response = b""
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                response += chunk
    except Exception as exc:
        logger.debug("proj socket call failed (%s): %s", type(exc).__name__, exc)


_HEALTH_BANNER = (
    "\u26a0 Hook router unreachable \u2014 todo/sync hooks will not fire this session"
    " (see: {detail}; set HOOKS_HEALTH_CHECK=0 to silence)"
)


def _check_router_health() -> None:
    """Probe router MCP socket; emit stderr banner if unreachable."""
    if os.environ.get("HOOKS_HEALTH_CHECK") == "0":
        return
    with contextlib.suppress(Exception):
        from server.lib.router_health import check_router_reachable

        ok, detail = asyncio.run(check_router_reachable())
        if not ok:
            msg = _HEALTH_BANNER.format(detail=detail)
            if sys.stderr.isatty():
                sys.stderr.write(f"\033[31m{msg}\033[0m\n")
            else:
                sys.stderr.write(f"{msg}\n")


def _cleanup_legacy_injected_hooks() -> None:
    """Remove cpm-injected hooks from ~/.claude/settings.json (one-time migration).

    Prior versions injected SessionStart hooks with ``# cpm:`` sentinel lines
    into settings.json. Now that hooks live in the plugin's hooks/hooks.json,
    those entries are redundant and should be cleaned up.
    """
    cfg = storage.load_config()
    if getattr(cfg, "settings_hooks_migrated", False):
        return

    settings_path = Path.home() / ".claude" / "settings.json"
    if not settings_path.exists():
        return

    try:
        raw = settings_path.read_text()
        data = json.loads(raw)
    except (OSError, json.JSONDecodeError):
        return

    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        return

    import re

    sentinel_re = re.compile(r"^\s*#\s*cpm:[A-Za-z0-9_.-]+\s*$", re.MULTILINE)
    changed = False

    for event, matchers in list(hooks.items()):
        if not isinstance(matchers, list):
            continue
        cleaned = []
        for matcher in matchers:
            keep = True
            for hook in matcher.get("hooks", []):
                cmd = hook.get("command", "")
                if sentinel_re.search(cmd):
                    keep = False
                    break
            if keep:
                cleaned.append(matcher)
            else:
                changed = True
        hooks[event] = cleaned
        if not cleaned:
            del hooks[event]

    if not changed:
        return

    if not hooks:
        del data["hooks"]

    try:
        tmp = settings_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n")
        tmp.replace(settings_path)
    except OSError:
        return

    # Mark migration done in proj.yaml
    try:
        proj_yaml = Path.home() / ".claude" / "proj.yaml"
        import yaml

        cfg_data = yaml.safe_load(proj_yaml.read_text()) or {}
        cfg_data["settings_hooks_migrated"] = True
        proj_yaml.write_text(yaml.dump(cfg_data, default_flow_style=False))
    except Exception:  # noqa: S110
        pass  # best-effort flag


def cmd_session_start(cwd: str | None, compact: bool) -> None:
    """Print project context to stdout for SessionStart hook injection.

    Also calls proj_load_session via the proj MCP socket so the MCP server's
    in-memory state is updated immediately (without requiring Claude to act on
    a text instruction).
    """
    if not storage.config_exists():
        return

    # One-time: remove legacy injected hooks from settings.json
    _cleanup_legacy_injected_hooks()

    cfg = storage.load_config()

    # Auto-detect project from cwd (session-only)
    detected: str | None = None
    if cwd:
        detected = ctx_detect_project_name(cwd)

    if not detected:
        return

    try:
        context = _build_context(cfg, detected, compact=compact)
        print(context)
        if compact:
            # Include session digest in compact mode (PreCompact hook)
            sess_dir = storage.sessions_dir(cfg, detected)
            if sess_dir.is_dir():
                files = sorted(sess_dir.glob("session-*.md"))
                selected = files[-3:] if len(files) > 3 else files
                if selected:
                    aggregated: dict[str, list[str]] = {
                        "decisions": [],
                        "questions": [],
                        "insights": [],
                    }
                    for f in selected:
                        try:
                            parsed = _parse_session(f.read_text())
                            for key in aggregated:
                                aggregated[key].extend(parsed[key])
                        except OSError:
                            continue
                    for key in aggregated:
                        aggregated[key] = _deduplicate(aggregated[key])
                    if aggregated["decisions"] or aggregated["questions"]:
                        print("\n### Session Digest (last 3)")
                        if aggregated["decisions"]:
                            print("**Decisions**: " + "; ".join(aggregated["decisions"][:5]))
                        if aggregated["questions"]:
                            print("**Open Questions**: " + "; ".join(aggregated["questions"][:3]))
    except FileNotFoundError:
        print("Warning: project config not found, skipping session context", file=sys.stderr)
        return

    # Activate the project in the MCP server process via socket call.
    # This ensures state.set_session_active() is set even if $CLAUDE_PROJECT_DIR
    # was missing at MCP startup (Layer 1), so all subsequent MCP tool calls
    # resolve the correct project without requiring Claude to call proj_load_session.
    _call_proj_socket("proj_load_session", {"name": detected})

    # Router health probe (replaces standalone session_start_router_health.py).
    _check_router_health()


def cmd_session_end(cwd: str | None) -> None:
    """Bump last_updated for the active project (async, no output needed)."""
    if not storage.config_exists():
        return
    cfg = storage.load_config()

    # Detect project from cwd (session-only)
    detected: str | None = None
    if cwd:
        detected = ctx_detect_project_name(cwd)
    if not detected:
        return
    try:
        meta = storage.load_meta(cfg, detected)
        today = str(date.today())
        if meta.dates.last_updated == today:
            return
        storage.save_meta(cfg, meta)
    except FileNotFoundError:
        print("Warning: project config not found, skipping session context", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="proj hook CLI")
    sub = parser.add_subparsers(dest="command")

    start = sub.add_parser("session-start")
    start.add_argument("--cwd", default=None)
    start.add_argument("--compact", action="store_true")

    end = sub.add_parser("session-end")
    end.add_argument("--cwd", default=None)

    args = parser.parse_args()

    if args.command == "session-start":
        cmd_session_start(args.cwd, args.compact)
    elif args.command == "session-end":
        cmd_session_end(args.cwd)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
