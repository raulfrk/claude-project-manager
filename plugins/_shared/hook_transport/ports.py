"""Single source of truth for plugin TCP fallback ports.

Reads from plugins/_shared/ports.yaml (sibling of this package). Validation
of uniqueness happens at commit time via policies/port_uniqueness.rego.
"""

from __future__ import annotations

from pathlib import Path

import yaml

# ports.yaml lives one dir above this package (plugins/_shared/ports.yaml in
# editable installs; sibling of hook_transport/ in wheel layout via
# pyproject.toml force-include).
_PORTS_PATH = Path(__file__).resolve().parent.parent / "ports.yaml"


def port_for(plugin_name: str) -> int:
    """Return the canonical TCP fallback port for a plugin.

    Raises KeyError if plugin_name is not in ports.yaml.
    """
    with _PORTS_PATH.open() as f:
        ports = yaml.safe_load(f) or {}
    if plugin_name not in ports:
        msg = f"unknown plugin {plugin_name!r}; not in {_PORTS_PATH}"
        raise KeyError(msg)
    return int(ports[plugin_name])
