"""Refresh vendored OpenAPI specs from their upstream URLs.

Invoked locally or by the monthly GitHub Actions cron at
``.github/workflows/openapi-refresh.yml``. The cron runs this in dry-run
mode on a fresh branch, commits the diff if any, and opens a PR for review.

Specs with ``x-cpm-source: manual`` (jira-dc, confluence-dc) are
hand-authored and skipped — there is no upstream to pull from.

Examples
--------
    # List everything under our control
    python -m test_contracts.sync_openapi list

    # Fetch latest + report diff vs vendored snapshot (no writes)
    python -m test_contracts.sync_openapi diff --plugin todoist

    # Overwrite vendored snapshot with upstream
    python -m test_contracts.sync_openapi refresh --plugin todoist

    # Refresh all non-manual specs
    python -m test_contracts.sync_openapi refresh --all

For the jira DC hand-authored spec, ``cross-check`` compares our declared
paths against the upstream WADL (Atlassian's only machine-readable
artifact for DC) and flags paths that no longer exist upstream::

    python -m test_contracts.sync_openapi cross-check --plugin jira
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class SpecSource:
    """Upstream source for a vendored OpenAPI spec."""

    plugin: str
    name: str
    vendored_path: Path
    upstream_url: str | None
    wadl_url: str | None = None

    @property
    def is_manual(self) -> bool:
        return self.upstream_url is None


SPECS: list[SpecSource] = [
    SpecSource(
        plugin="todoist",
        name="todoist-v1",
        vendored_path=REPO_ROOT / "plugins/todoist/server/tests/contracts/openapi/todoist-v1.json",
        upstream_url="https://developer.todoist.com/openapi.json",
    ),
    SpecSource(
        plugin="trello",
        name="trello-v1",
        vendored_path=REPO_ROOT / "plugins/trello/server/tests/contracts/openapi/trello-v1.json",
        upstream_url="https://api.apis.guru/v2/specs/trello.com/1.0/openapi.json",
    ),
    SpecSource(
        plugin="confluence-cloud",
        name="confluence-cloud-v3",
        vendored_path=REPO_ROOT
        / "plugins/confluence/server/tests/contracts/openapi/confluence-cloud-v3.json",
        upstream_url="https://developer.atlassian.com/cloud/confluence/swagger.v3.json",
    ),
    SpecSource(
        plugin="jira",
        name="jira-dc-v2",
        vendored_path=REPO_ROOT / "plugins/jira/server/tests/contracts/openapi/jira-dc-v2.json",
        upstream_url=None,  # manual
        wadl_url="https://docs.atlassian.com/software/jira/docs/api/REST/9.17.0/jira-rest-plugin.wadl",
    ),
    SpecSource(
        plugin="confluence-dc",
        name="confluence-dc-v1",
        vendored_path=REPO_ROOT
        / "plugins/confluence/server/tests/contracts/openapi/confluence-dc-v1.json",
        upstream_url=None,  # manual
    ),
]


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return resp.read()


def _load_json_bytes(raw: bytes) -> dict:
    return json.loads(raw)


def _normalise_spec_for_diff(spec: dict) -> str:
    """Stable pretty-printed JSON so diffs don't churn on key order."""
    return json.dumps(spec, sort_keys=True, indent=2) + "\n"


def cmd_list(_: argparse.Namespace) -> int:
    for src in SPECS:
        manual = " [manual]" if src.is_manual else ""
        print(f"  {src.plugin:20} {src.name:25}{manual}")
        if src.upstream_url:
            print(f"    upstream: {src.upstream_url}")
        if src.wadl_url:
            print(f"    wadl:     {src.wadl_url}")
    return 0


def _iter_selected(args: argparse.Namespace) -> Iterable[SpecSource]:
    if getattr(args, "all", False):
        return SPECS
    if args.plugin:
        return [s for s in SPECS if s.plugin == args.plugin]
    return []


def cmd_diff(args: argparse.Namespace) -> int:
    selected = list(_iter_selected(args))
    if not selected:
        print("error: pass --plugin NAME or --all", file=sys.stderr)
        return 2

    any_diff = False
    for src in selected:
        if src.is_manual:
            print(f"{src.plugin}: skipped (manual spec, no upstream)")
            continue
        assert src.upstream_url is not None
        upstream = _load_json_bytes(_fetch(src.upstream_url))
        vendored = json.loads(src.vendored_path.read_text())
        up_txt = _normalise_spec_for_diff(upstream)
        v_txt = _normalise_spec_for_diff(vendored)
        if up_txt == v_txt:
            print(f"{src.plugin}: in sync ({src.vendored_path.stat().st_size} B)")
        else:
            any_diff = True
            up_paths = set(upstream.get("paths", {}).keys())
            v_paths = set(vendored.get("paths", {}).keys())
            added = sorted(up_paths - v_paths)
            removed = sorted(v_paths - up_paths)
            print(f"{src.plugin}: DRIFT — upstream differs from vendored")
            if added:
                print(f"  + paths added upstream ({len(added)}):")
                for p in added[:10]:
                    print(f"      {p}")
                if len(added) > 10:
                    print(f"      ... and {len(added) - 10} more")
            if removed:
                print(f"  - paths removed upstream ({len(removed)}):")
                for p in removed[:10]:
                    print(f"      {p}")
                if len(removed) > 10:
                    print(f"      ... and {len(removed) - 10} more")
            common = up_paths & v_paths
            print(f"  = paths unchanged: {len(common)}")
    return 1 if any_diff else 0


def cmd_refresh(args: argparse.Namespace) -> int:
    selected = list(_iter_selected(args))
    if not selected:
        print("error: pass --plugin NAME or --all", file=sys.stderr)
        return 2

    for src in selected:
        if src.is_manual:
            print(f"{src.plugin}: skipped (manual spec)")
            continue
        assert src.upstream_url is not None
        print(f"{src.plugin}: fetching {src.upstream_url}")
        raw = _fetch(src.upstream_url)
        spec = _load_json_bytes(raw)
        text = _normalise_spec_for_diff(spec)
        prev_size = src.vendored_path.stat().st_size if src.vendored_path.exists() else 0
        src.vendored_path.write_text(text)
        print(
            f"{src.plugin}: wrote {src.vendored_path.relative_to(REPO_ROOT)} "
            f"({prev_size} → {src.vendored_path.stat().st_size} B)"
        )
    return 0


def _wadl_paths(wadl_xml: bytes) -> set[tuple[str, str]]:
    """Extract (method, full_path) pairs from a Jersey WADL document."""
    root = ET.fromstring(wadl_xml)
    ns = {"wadl": "http://wadl.dev.java.net/2009/02"}
    out: set[tuple[str, str]] = set()

    resources_el = root.find("wadl:resources", ns)
    if resources_el is None:
        return out
    base = resources_el.attrib.get("base", "")

    # base typically looks like "http://example.com:8080/jira/rest/"
    # we want paths starting with "/rest/…"
    base_path = "/rest/" if base.rstrip("/").endswith("/rest") else ""

    def walk(resource: ET.Element, prefix: str) -> None:
        path = resource.attrib.get("path", "").lstrip("/")
        full = f"{prefix.rstrip('/')}/{path}" if path else prefix
        for method_el in resource.findall("wadl:method", ns):
            method = method_el.attrib.get("name", "").upper()
            if method:
                normalised = "/" + full.lstrip("/")
                out.add((method, normalised))
        for child in resource.findall("wadl:resource", ns):
            walk(child, full)

    for top in resources_el.findall("wadl:resource", ns):
        walk(top, base_path.rstrip("/"))

    return out


def cmd_cross_check(args: argparse.Namespace) -> int:
    """For hand-authored specs, cross-reference paths against upstream WADL if present."""
    selected = list(_iter_selected(args))
    if not selected:
        print("error: pass --plugin NAME or --all", file=sys.stderr)
        return 2

    any_missing = False
    for src in selected:
        if not src.wadl_url:
            print(f"{src.plugin}: no WADL cross-check source — skipped")
            continue
        print(f"{src.plugin}: fetching WADL {src.wadl_url}")
        wadl_bytes = _fetch(src.wadl_url)
        upstream_ops = _wadl_paths(wadl_bytes)

        vendored = json.loads(src.vendored_path.read_text())
        vendored_ops: set[tuple[str, str]] = set()
        for url, path_obj in vendored.get("paths", {}).items():
            if not isinstance(path_obj, dict):
                continue
            for method in path_obj:
                if method in {"parameters", "summary", "description", "servers"}:
                    continue
                vendored_ops.add((method.upper(), url))

        # Normalise vendored paths: convert {issueKey} → {placeholder} for comparison
        # because WADL uses {issueIdOrKey} etc. with different names.
        def _canonicalise(entries: set[tuple[str, str]]) -> set[tuple[str, str]]:
            import re

            out: set[tuple[str, str]] = set()
            for m, u in entries:
                canon = re.sub(r"\{[^}]+\}", "{x}", u)
                out.add((m, canon))
            return out

        missing = _canonicalise(vendored_ops) - _canonicalise(upstream_ops)
        if missing:
            any_missing = True
            print(f"{src.plugin}: endpoints in vendored spec NOT found in upstream WADL:")
            for method, url in sorted(missing):
                print(f"  {method:6} {url}")
        else:
            print(
                f"{src.plugin}: all {len(vendored_ops)} vendored endpoints exist in upstream WADL"
            )

    return 1 if any_missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="sync_openapi",
        description="Refresh vendored OpenAPI specs from upstream sources.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub_list = sub.add_parser("list", help="List all spec sources.")
    sub_list.set_defaults(func=cmd_list)

    for name, fn, help_text in [
        ("diff", cmd_diff, "Fetch upstream and diff against vendored snapshot."),
        ("refresh", cmd_refresh, "Fetch upstream and overwrite vendored snapshot."),
        (
            "cross-check",
            cmd_cross_check,
            "For hand-authored specs, validate paths against upstream WADL.",
        ),
    ]:
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--plugin", help="Plugin name (e.g. todoist, trello, jira)")
        p.add_argument("--all", action="store_true", help="Apply to every configured spec")
        p.set_defaults(func=fn)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
