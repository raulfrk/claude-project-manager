"""Shared dual-transport library for MCP plugin inter-server hook communication."""

from hook_transport.dual_transport import run_dual
from hook_transport.http_hook_handler import create_hook_app
from hook_transport.ports import port_for
from hook_transport.socket_path import (
    legacy_socket_path,
    socket_dir,
    socket_glob,
    socket_path,
    tmp_dir,
)

__all__ = [
    "create_hook_app",
    "legacy_socket_path",
    "port_for",
    "run_dual",
    "socket_dir",
    "socket_glob",
    "socket_path",
    "tmp_dir",
]
