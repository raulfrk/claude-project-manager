"""Test fixture helpers for external-integration plugins.

Autodiscovers every `get_client` binding in a plugin's tool package so tests
can patch them all without a hand-maintained list. Replaces the brittle
`_GET_CLIENT_LOCATIONS` pattern that had to be updated whenever a new tool
module was added.
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import Any


def discover_get_client_locations(
    tools_package: str = "server.tools",
    client_module: str | None = "server.lib.client",
) -> list[str]:
    """Return dotted paths for every symbol named `get_client` in a plugin.

    Walks `tools_package` and its direct submodules, plus an optional
    `client_module`. A module contributes a location only if it actually
    binds the name `get_client` (either defines it or re-exports via
    `from ... import get_client`).

    Parameters
    ----------
    tools_package:
        Dotted path to the plugin's tools package (e.g. ``"server.tools"``).
    client_module:
        Dotted path to the module that defines the canonical
        ``get_client`` factory. Pass ``None`` to skip.

    Returns
    -------
    List of dotted paths suitable for ``mocker.patch`` /
    ``monkeypatch.setattr``, e.g.
    ``["server.lib.client.get_client", "server.tools.issues.get_client", ...]``.
    """
    locations: list[str] = []

    if client_module is not None:
        module = importlib.import_module(client_module)
        if hasattr(module, "get_client"):
            locations.append(f"{client_module}.get_client")

    pkg = importlib.import_module(tools_package)
    pkg_path = getattr(pkg, "__path__", None)
    if pkg_path is None:
        raise TypeError(f"{tools_package!r} is not a package")

    for info in pkgutil.iter_modules(pkg_path, prefix=f"{tools_package}."):
        module = importlib.import_module(info.name)
        if hasattr(module, "get_client"):
            locations.append(f"{info.name}.get_client")

    return locations


def patch_get_client_everywhere(
    mocker: Any,
    *,
    return_value: Any,
    tools_package: str = "server.tools",
    client_module: str | None = "server.lib.client",
) -> list[str]:
    """Patch every discovered ``get_client`` location to return ``return_value``.

    Uses the ``mocker`` fixture's ``patch`` method (pytest-mock). Returns the
    list of patched locations so callers can assert on coverage if desired.
    """
    locations = discover_get_client_locations(tools_package, client_module)
    for loc in locations:
        mocker.patch(loc, return_value=return_value)
    return locations


def setattr_get_client_everywhere(
    monkeypatch: Any,
    factory: Any,
    *,
    tools_package: str = "server.tools",
    client_module: str | None = "server.lib.client",
) -> list[str]:
    """MonkeyPatch variant — sets ``get_client`` to ``factory`` at every location.

    ``factory`` is typically a zero-arg callable returning a mock client.
    Use when the test suite relies on ``pytest.MonkeyPatch`` rather than
    ``pytest-mock``.
    """
    locations = discover_get_client_locations(tools_package, client_module)
    for loc in locations:
        monkeypatch.setattr(loc, factory)
    return locations
