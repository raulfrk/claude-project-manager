"""Tests for the get_client autodiscovery helper."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from test_contracts.fixtures import (
    discover_get_client_locations,
    patch_get_client_everywhere,
    setattr_get_client_everywhere,
)


def _install_package(name: str, submodules: dict[str, dict[str, object]]) -> None:
    """Register a synthetic package + submodules in sys.modules for discovery."""
    pkg = types.ModuleType(name)
    pkg.__path__ = []  # type: ignore[attr-defined]
    sys.modules[name] = pkg

    for sub_name, attrs in submodules.items():
        full = f"{name}.{sub_name}"
        mod = types.ModuleType(full)
        for key, value in attrs.items():
            setattr(mod, key, value)
        sys.modules[full] = mod


@pytest.fixture()
def fake_plugin(monkeypatch: pytest.MonkeyPatch) -> str:
    """Install a throwaway `fakeplugin.tools.*` package hierarchy.

    Two modules bind `get_client`; one does not. Returns the tools package path.
    """
    # Root namespace is unique per test run to avoid collisions.
    root = "fakeplugin_af"

    # Build packages manually so pkgutil can walk them.
    ns = types.ModuleType(root)
    ns.__path__ = [f"/tmp/{root}"]  # type: ignore[attr-defined]
    sys.modules[root] = ns

    tools_pkg = types.ModuleType(f"{root}.tools")
    tools_pkg.__path__ = [f"/tmp/{root}/tools"]  # type: ignore[attr-defined]
    sys.modules[f"{root}.tools"] = tools_pkg
    ns.tools = tools_pkg  # type: ignore[attr-defined]

    def _dummy_get_client() -> object:
        return object()

    alpha = types.ModuleType(f"{root}.tools.alpha")
    alpha.get_client = _dummy_get_client  # type: ignore[attr-defined]
    sys.modules[f"{root}.tools.alpha"] = alpha
    tools_pkg.alpha = alpha  # type: ignore[attr-defined]

    beta = types.ModuleType(f"{root}.tools.beta")
    beta.get_client = _dummy_get_client  # type: ignore[attr-defined]
    sys.modules[f"{root}.tools.beta"] = beta
    tools_pkg.beta = beta  # type: ignore[attr-defined]

    gamma = types.ModuleType(f"{root}.tools.gamma")
    # gamma intentionally has no get_client
    sys.modules[f"{root}.tools.gamma"] = gamma
    tools_pkg.gamma = gamma  # type: ignore[attr-defined]

    client_mod = types.ModuleType(f"{root}.lib_client")
    client_mod.get_client = _dummy_get_client  # type: ignore[attr-defined]
    sys.modules[f"{root}.lib_client"] = client_mod
    ns.lib_client = client_mod  # type: ignore[attr-defined]

    # Patch pkgutil.iter_modules to yield the synthetic tool modules.
    def _fake_iter_modules(path: list[str], prefix: str = ""):  # type: ignore[no-untyped-def]
        if path == tools_pkg.__path__:
            for name in ("alpha", "beta", "gamma"):
                yield types.SimpleNamespace(module_finder=None, name=f"{prefix}{name}", ispkg=False)
        else:
            # Fall through to real iter_modules for anything else.
            yield from ()

    import pkgutil

    monkeypatch.setattr(pkgutil, "iter_modules", _fake_iter_modules)

    yield f"{root}.tools"

    for mod_name in list(sys.modules):
        if mod_name == root or mod_name.startswith(f"{root}."):
            sys.modules.pop(mod_name, None)


def test_discover_skips_modules_without_get_client(fake_plugin: str) -> None:
    root = fake_plugin.removesuffix(".tools")
    locations = discover_get_client_locations(
        tools_package=fake_plugin, client_module=f"{root}.lib_client"
    )
    assert f"{root}.lib_client.get_client" in locations
    assert f"{fake_plugin}.alpha.get_client" in locations
    assert f"{fake_plugin}.beta.get_client" in locations
    assert f"{fake_plugin}.gamma.get_client" not in locations


def test_discover_without_client_module(fake_plugin: str) -> None:
    locations = discover_get_client_locations(tools_package=fake_plugin, client_module=None)
    for loc in locations:
        assert "lib_client" not in loc


def test_discover_raises_on_non_package() -> None:
    # `sys` is a module, not a package — no __path__.
    with pytest.raises(TypeError, match="is not a package"):
        discover_get_client_locations(tools_package="sys", client_module=None)


def test_patch_get_client_everywhere(fake_plugin: str) -> None:
    pytest_mock = pytest.importorskip("pytest_mock")
    # Build a fresh mocker fixture via pytest_mock's factory isn't trivial
    # here; instead stub a minimal mocker with a .patch method.
    patched: list[tuple[str, object]] = []

    class _StubMocker:
        def patch(self, target: str, *, return_value: object) -> None:
            patched.append((target, return_value))

    del pytest_mock  # silence unused
    mock_client = MagicMock()
    root = fake_plugin.removesuffix(".tools")

    locations = patch_get_client_everywhere(
        _StubMocker(),
        return_value=mock_client,
        tools_package=fake_plugin,
        client_module=f"{root}.lib_client",
    )

    assert len(patched) == len(locations) == 3
    assert all(rv is mock_client for _, rv in patched)


def test_setattr_get_client_everywhere(fake_plugin: str, monkeypatch: pytest.MonkeyPatch) -> None:
    root = fake_plugin.removesuffix(".tools")
    factory_result = object()

    def _factory() -> object:
        return factory_result

    locations = setattr_get_client_everywhere(
        monkeypatch,
        _factory,
        tools_package=fake_plugin,
        client_module=f"{root}.lib_client",
    )

    assert len(locations) == 3
    for loc in locations:
        module_path, _, attr = loc.rpartition(".")
        mod = sys.modules[module_path]
        assert getattr(mod, attr) is _factory
