"""CLI entrypoint for hooks (shares lib/ with MCP server, no MCP stdio needed)."""

from __future__ import annotations

import argparse
import sys
from datetime import date

from server.lib import storage
from server.tools.context import _build_context, ctx_detect_project_name


def cmd_session_start(cwd: str | None, compact: bool) -> None:
    """Print project context to stdout for SessionStart hook injection."""
    if not storage.config_exists():
        return

    cfg = storage.load_config()
    index = storage.load_index(cfg)

    # Auto-detect project from cwd (session-only: do NOT persist to disk)
    if cwd and not index.active:
        name = ctx_detect_project_name(cwd)
        if name:
            index.active = name

    if not index.active:
        return

    try:
        context = _build_context(cfg, index.active, compact=compact)
        print(context)
        if not compact:
            print(f'\n⚡ **Activate**: Call `proj_load_session("{index.active}")` to register this project for MCP tools this session.')
    except FileNotFoundError:
        print("Warning: project config not found, skipping session context", file=sys.stderr)


def cmd_session_end(cwd: str | None) -> None:
    """Bump last_updated for the active project (async, no output needed)."""
    if not storage.config_exists():
        return
    cfg = storage.load_config()
    index = storage.load_index(cfg)
    if not index.active:
        return
    try:
        meta = storage.load_meta(cfg, index.active)
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
