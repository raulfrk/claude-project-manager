"""CLI entrypoint for hooks (shares lib/ with MCP server, no MCP stdio needed)."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from server.lib import storage
from server.tools.context import _build_context, ctx_detect_project_name
from server.tools.digest import _deduplicate, _parse_session


def cmd_session_start(cwd: str | None, compact: bool) -> None:
    """Print project context to stdout for SessionStart hook injection."""
    if not storage.config_exists():
        return

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
                    aggregated: dict[str, list[str]] = {"decisions": [], "questions": [], "insights": []}
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
        else:
            print(f'\n⚡ **Activate**: Call `proj_load_session("{detected}")` to register this project for MCP tools this session.')
    except FileNotFoundError:
        print("Warning: project config not found, skipping session context", file=sys.stderr)


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
