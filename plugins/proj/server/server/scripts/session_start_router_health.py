"""Claude Code SessionStart hook: probe the hook router socket.

Standalone script. On success, exits silently with code 0. On failure, emits a
red ANSI banner to stderr describing the problem and a fix hint. Always exits
0 so the session is never failed by this hook.

Set ``HOOKS_HEALTH_CHECK=0`` to silence the probe entirely.

CLI::

    python3 session_start_router_health.py
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import sys
from pathlib import Path

# --- sys.path bootstrap (runs before any server / hook_dispatch imports) ---
_script_path = Path(__file__).resolve()
# .../server/server/scripts/session_start_router_health.py
# parents[0] = scripts, [1] = server (package), [2] = server (src root)
_server_src = _script_path.parents[2]
if str(_server_src) not in sys.path:
    sys.path.insert(0, str(_server_src))

# _shared is sibling to plugins/proj at the plugin tree: plugins/_shared
# Installed layout keeps _shared as an installed wheel, so this is best-effort.
_plugin_cache_dir = _script_path.parents[3]
_shared_candidate = _plugin_cache_dir.parent / "_shared"
if _shared_candidate.is_dir() and str(_shared_candidate) not in sys.path:
    sys.path.insert(0, str(_shared_candidate))


_BANNER_TMPL = (
    "\u26a0 Hook router unreachable — todo/sync hooks will not fire this session"
    " (see: {detail}; set HOOKS_HEALTH_CHECK=0 to silence)"
)
_ANSI_RED = "\033[31m"
_ANSI_RESET = "\033[0m"


def _emit_banner(detail: str) -> None:
    msg = _BANNER_TMPL.format(detail=detail)
    if sys.stderr.isatty():
        sys.stderr.write(f"{_ANSI_RED}{msg}{_ANSI_RESET}\n")
    else:
        sys.stderr.write(f"{msg}\n")


async def _run() -> None:
    from server.lib.router_health import check_router_reachable

    ok, detail = await check_router_reachable()
    if not ok:
        _emit_banner(detail)


def main(argv: list[str] | None = None) -> int:
    del argv
    if os.environ.get("HOOKS_HEALTH_CHECK") == "0":
        return 0
    with contextlib.suppress(Exception):
        asyncio.run(_run())
    return 0


if __name__ == "__main__":
    sys.exit(main())
