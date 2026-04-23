"""Load vendored OpenAPI specs and build EndpointContract objects from them.

Plugins vendor their API's OpenAPI spec under
``<plugin>/server/tests/contracts/openapi/<name>.json``. This module reads
those specs and exposes helpers so tests can reference endpoints by
``operationId`` rather than hand-authoring schemas.

Vendored specs come from two sources:

- **Upstream**: pulled from a public URL (e.g. developer.atlassian.com,
  apis.guru). Refreshed by ``sync_openapi.py``.
- **Hand-authored**: for plugins/deployments with no public spec (Jira DC,
  Confluence DC). Marked at the root with
  ``"x-cpm-source": "manual"``. Sync script skips refresh but may
  cross-check against a WADL or similar source of truth.

All specs, regardless of source, flow through the same helpers so tests
look identical across plugins.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from test_contracts.base import EndpointContract


class SpecError(LookupError):
    """Raised when an operation, path, or response can't be resolved in a spec."""


@lru_cache(maxsize=16)
def load(spec_path: str | Path) -> dict[str, Any]:
    """Read + parse a vendored OpenAPI JSON spec. Cached per path."""
    path = Path(spec_path)
    with path.open() as f:
        spec: dict[str, Any] = json.load(f)
    return spec


def _find_operation(spec: dict[str, Any], operation_id: str) -> tuple[str, str, dict[str, Any]]:
    """Return (url_pattern, method, operation_object) for a given operationId."""
    for url_pattern, path_obj in spec.get("paths", {}).items():
        if not isinstance(path_obj, dict):
            continue
        for method, op in path_obj.items():
            if method in {"parameters", "summary", "description", "servers"}:
                continue
            if isinstance(op, dict) and op.get("operationId") == operation_id:
                return url_pattern, method.upper(), op
    raise SpecError(f"operationId {operation_id!r} not found in spec")


def _find_operation_by_path(spec: dict[str, Any], method: str, url_pattern: str) -> dict[str, Any]:
    """Return the operation object for a given (method, url_pattern) pair."""
    paths = spec.get("paths", {})
    path_obj = paths.get(url_pattern)
    if not isinstance(path_obj, dict):
        raise SpecError(f"path {url_pattern!r} not found in spec")
    op = path_obj.get(method.lower())
    if not isinstance(op, dict):
        raise SpecError(f"{method.upper()} not defined on {url_pattern!r} in spec")
    return op


def _resolve_ref(spec: dict[str, Any], ref: str) -> dict[str, Any]:
    """Follow a $ref like '#/components/schemas/Foo'."""
    if not ref.startswith("#/"):
        raise SpecError(f"external $ref not supported: {ref!r}")
    node: Any = spec
    for part in ref[2:].split("/"):
        if not isinstance(node, dict) or part not in node:
            raise SpecError(f"broken $ref: {ref!r}")
        node = node[part]
    if not isinstance(node, dict):
        raise SpecError(f"$ref does not resolve to object: {ref!r}")
    return node


def _schema_for_content(spec: dict[str, Any], content: dict[str, Any] | None) -> dict[str, Any]:
    """Return the JSON schema fragment for a content map (prefer application/json).

    ``$ref`` references are expanded inline — the returned schema is
    self-contained so callers don't need a Registry to validate against it.
    Cycles are short-circuited at a reasonable depth.
    """
    if not content:
        return {}
    preferred = content.get("application/json") or next(iter(content.values()))
    schema = preferred.get("schema", {}) if isinstance(preferred, dict) else {}
    if not isinstance(schema, dict):
        return {}
    return _expand_refs(spec, schema, seen=set())


def _expand_refs(spec: dict[str, Any], node: Any, seen: set[str], depth: int = 0) -> Any:
    """Return a deep copy of ``node`` with every ``$ref`` resolved in-place.

    Cycle detection: the same ``$ref`` seen twice along a single path short-
    circuits to ``{}`` so the validator accepts any value at that point.
    Depth limit 20 to prevent runaway expansion.
    """
    if depth > 20:
        return {}
    if isinstance(node, dict):
        if "$ref" in node and isinstance(node["$ref"], str):
            ref = node["$ref"]
            if ref in seen:
                return {}
            target = _resolve_ref(spec, ref)
            merged: dict[str, Any] = {k: v for k, v in node.items() if k != "$ref"}
            expanded = _expand_refs(spec, target, seen | {ref}, depth + 1)
            if isinstance(expanded, dict):
                merged = {**expanded, **merged}
            return merged
        return {k: _expand_refs(spec, v, seen, depth + 1) for k, v in node.items()}
    if isinstance(node, list):
        return [_expand_refs(spec, item, seen, depth + 1) for item in node]
    return node


def response_schema_for(
    spec: dict[str, Any], operation_id: str, status: str | int = "2xx"
) -> dict[str, Any]:
    """Return the JSON schema for a given operation's response.

    ``status`` accepts "200", "201", "204", or "2xx" (takes the first 2XX
    response found). Returns ``{}`` for responses with no body (e.g. 204).
    """
    _, _, op = _find_operation(spec, operation_id)
    responses = op.get("responses", {})
    if not isinstance(responses, dict):
        return {}

    key = str(status)
    if key == "2xx":
        for resp_key in responses:
            if resp_key.startswith("2"):
                key = resp_key
                break

    resp = responses.get(key) or {}
    if isinstance(resp, dict) and "$ref" in resp:
        resp = _resolve_ref(spec, resp["$ref"])
    content = resp.get("content") if isinstance(resp, dict) else None
    return _schema_for_content(spec, content)


def request_schema_for(spec: dict[str, Any], operation_id: str) -> dict[str, Any] | None:
    """Return the JSON schema for an operation's request body, or None if none."""
    _, _, op = _find_operation(spec, operation_id)
    body = op.get("requestBody")
    if not isinstance(body, dict):
        return None
    if "$ref" in body:
        body = _resolve_ref(spec, body["$ref"])
    content = body.get("content")
    schema = _schema_for_content(spec, content if isinstance(content, dict) else None)
    return schema or None


def _success_status_for(op: dict[str, Any]) -> int:
    """Pick a canonical 2xx status code from an operation's responses."""
    responses = op.get("responses", {}) or {}
    for key in responses:
        if isinstance(key, str) and key.startswith("2"):
            try:
                return int(key)
            except ValueError:
                continue
    return 200


def endpoint_contract(
    spec_path: str | Path,
    method: str,
    url_pattern: str,
    *,
    required_headers: dict[str, str] | None = None,
    auth_style: str = "bearer",
    status: str | int = "2xx",
) -> EndpointContract:
    """Build an EndpointContract from a vendored OpenAPI spec.

    Looks up an operation by ``(method, url_pattern)`` — the same fields that
    already exist on the caller's contract — and pulls request/response
    schemas from the vendored spec.

    Parameters
    ----------
    spec_path:
        Absolute or relative path to the vendored spec JSON file.
    method:
        HTTP method (GET/POST/PUT/DELETE).
    url_pattern:
        URL path pattern (must match a key in the spec's ``paths`` map).
    required_headers:
        Headers the client is expected to send. Caller supplies because
        auth style is plugin-specific and often token-templated.
    auth_style:
        One of ``"bearer"``, ``"basic"``, ``"query_params"``.
    status:
        Which response status's schema to pull. Default ``"2xx"`` — first
        2XX code found. Pass explicit ``"204"`` etc. for no-body responses.
    """
    spec = load(spec_path)
    op = _find_operation_by_path(spec, method, url_pattern)
    success = _success_status_for(op) if status == "2xx" else int(status)
    return EndpointContract(
        method=method.upper(),
        url_pattern=url_pattern,
        required_headers=required_headers or {},
        auth_style=auth_style,
        request_schema=_request_schema_from_op(spec, op),
        response_schema=_response_schema_from_op(spec, op, status=success),
        response_status=success,
    )


def _response_schema_from_op(
    spec: dict[str, Any], op: dict[str, Any], status: int
) -> dict[str, Any]:
    responses = op.get("responses", {}) or {}
    resp = responses.get(str(status)) or {}
    if isinstance(resp, dict) and "$ref" in resp:
        resp = _resolve_ref(spec, resp["$ref"])
    content = resp.get("content") if isinstance(resp, dict) else None
    return _schema_for_content(spec, content if isinstance(content, dict) else None)


def _request_schema_from_op(spec: dict[str, Any], op: dict[str, Any]) -> dict[str, Any] | None:
    body = op.get("requestBody")
    if not isinstance(body, dict):
        return None
    if "$ref" in body:
        body = _resolve_ref(spec, body["$ref"])
    content = body.get("content")
    schema = _schema_for_content(spec, content if isinstance(content, dict) else None)
    return schema or None


def is_manual_spec(spec: dict[str, Any]) -> bool:
    """Whether this spec was hand-authored (skip in refresh cron)."""
    return spec.get("x-cpm-source") == "manual"


def list_operations(spec: dict[str, Any]) -> list[tuple[str, str, str]]:
    """Return [(operation_id, method, url_pattern), ...] for every operation in a spec."""
    out: list[tuple[str, str, str]] = []
    for url_pattern, path_obj in spec.get("paths", {}).items():
        if not isinstance(path_obj, dict):
            continue
        for method, op in path_obj.items():
            if method in {"parameters", "summary", "description", "servers"}:
                continue
            if isinstance(op, dict) and "operationId" in op:
                out.append((op["operationId"], method.upper(), url_pattern))
    return out


class OpenAPISchemaValidator:
    """Validates request/response bodies against OpenAPI-derived JSON Schemas.

    Uses ``jsonschema`` Draft 2020-12 semantics (respects ``required``, runs
    type checks). Expects schemas that are already ref-expanded — schemas
    built by :func:`endpoint_contract` have ``$ref`` pre-resolved inline.
    Construct once per spec and reuse across assertions.
    """

    def __init__(self, spec: dict[str, Any]) -> None:
        from jsonschema import Draft202012Validator

        self._spec = spec
        self._validator_cls = Draft202012Validator

    def validate(self, body: Any, schema: dict[str, Any]) -> None:
        """Raise ``jsonschema.ValidationError`` if ``body`` doesn't match ``schema``.

        If ``schema`` still contains ``$ref``, it's expanded first against the
        spec so callers who hand-craft partial schemas still work.
        """
        expanded = _expand_refs(self._spec, schema, seen=set())
        self._validator_cls(expanded).validate(body)

    def is_valid(self, body: Any, schema: dict[str, Any]) -> bool:
        """Return True iff ``body`` conforms to ``schema``."""
        expanded = _expand_refs(self._spec, schema, seen=set())
        return self._validator_cls(expanded).is_valid(body)


def validator_for(spec_path: str | Path) -> OpenAPISchemaValidator:
    """Build a cached OpenAPISchemaValidator for a vendored spec."""
    return OpenAPISchemaValidator(load(spec_path))
