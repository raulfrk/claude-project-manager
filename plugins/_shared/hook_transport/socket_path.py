"""Single source of truth for cpm tmp dir + Unix socket bind / glob paths.

All cpm production code resolves tmp paths and socket paths through this
helper. Hardcoded ``"/tmp"`` literals and bare ``os.environ.get("TMPDIR", ...)``
calls in production are forbidden by the ``forbid-tmpdir-drift`` pre-commit
hook (see ``scripts/check_tmpdir_drift.sh``); use the helpers below instead.

Public API
----------
- ``tmp_dir()`` — generic cpm tmp dir wrapper (currently aliases ``socket_dir``).
- ``socket_dir()`` — directory that holds Unix socket bind files.
- ``socket_path(plugin, pid)`` — full bind path for a given plugin + pid.
- ``socket_glob(plugin)`` — filename glob for fallback resolvers.
- ``legacy_socket_path(plugin)`` — no-PID fallback path (last-resort lookup).

Resolution semantics
--------------------
``socket_dir()`` returns ``Path(tempfile.gettempdir())``. ``tempfile`` already
honors ``TMPDIR`` / ``TMP`` / ``TEMP`` env vars and falls back to a
platform-appropriate default (``/tmp`` on POSIX), so this helper does NOT
re-implement the env-var dance. Callers that monkeypatch
``tempfile.gettempdir`` in tests automatically affect this helper too.

``tmp_dir`` is currently a thin alias for ``socket_dir`` so the two semantic
buckets (generic tmpfiles vs. socket bind dirs) can diverge later without a
follow-up callsite migration.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

__all__ = ["legacy_socket_path", "socket_dir", "socket_glob", "socket_path", "tmp_dir"]


_PLUGIN_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SOCKET_PREFIX = "claude-cpm-"


def _validate_plugin_name(plugin: str) -> None:
    """Raise ValueError if ``plugin`` is not a valid plugin identifier.

    Plugin names appear in socket filenames and must be filesystem-safe.
    Pattern: a lowercase letter followed by lowercase letters, digits, or
    underscores. Hyphens, dots, slashes, uppercase, and whitespace all reject.
    """
    if not _PLUGIN_NAME_RE.fullmatch(plugin):
        raise ValueError(f"invalid plugin name {plugin!r}: must match ^[a-z][a-z0-9_]*$")


def socket_dir() -> Path:
    """Return the directory that holds Unix socket bind files.

    Resolves via ``tempfile.gettempdir()`` so ``TMPDIR`` / ``TMP`` / ``TEMP``
    env vars are honored and tests can monkeypatch a single chokepoint.
    """
    return Path(tempfile.gettempdir())


def tmp_dir() -> Path:
    """Return the cpm tmp directory.

    Currently an alias for :func:`socket_dir`; reserved for future divergence
    (e.g. if generic tmpfiles move to a per-user subdir while socket binds
    stay at the root tempdir for shorter path length).
    """
    return socket_dir()


def socket_path(plugin: str, pid: int) -> Path:
    """Return the Unix socket bind path for ``plugin`` at process ``pid``.

    Format: ``<socket_dir>/claude-cpm-<plugin>-<pid>.sock``.

    Raises:
        ValueError: if ``plugin`` does not match ``^[a-z][a-z0-9_]*$``.
    """
    _validate_plugin_name(plugin)
    return socket_dir() / f"{_SOCKET_PREFIX}{plugin}-{pid}.sock"


def legacy_socket_path(plugin: str) -> Path:
    """Return the no-PID fallback socket path for ``plugin``.

    Format: ``<socket_dir>/claude-cpm-<plugin>.sock`` (no pid suffix).

    Used by fallback resolvers in proj tools when no PID-tagged socket is
    found via the registry file or the ``socket_glob`` scan (last-resort
    lookup before failing the call).

    Raises:
        ValueError: if ``plugin`` does not match ``^[a-z][a-z0-9_]*$``.
    """
    _validate_plugin_name(plugin)
    return socket_dir() / f"{_SOCKET_PREFIX}{plugin}.sock"


def socket_glob(plugin: str) -> str:
    """Return a filename glob that matches any pid-tagged socket for ``plugin``.

    Use as ``socket_dir().glob(socket_glob(plugin))`` in fallback resolvers
    that scan for the newest socket when the registry file is missing.

    Raises:
        ValueError: if ``plugin`` does not match ``^[a-z][a-z0-9_]*$``.
    """
    _validate_plugin_name(plugin)
    return f"{_SOCKET_PREFIX}{plugin}-*.sock"
