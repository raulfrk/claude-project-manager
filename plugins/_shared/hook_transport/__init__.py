"""Shared dual-transport library for MCP plugin inter-server hook communication."""

from hook_transport.dual_transport import run_dual
from hook_transport.http_hook_handler import create_hook_app

__all__ = ["create_hook_app", "run_dual"]
