"""Assertion helpers for validating requests and responses against contracts."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import httpx

    from test_contracts.base import EndpointContract

logger = logging.getLogger("test_contracts")


def _match_url_pattern(url: str, pattern: str, path_params: dict[str, str] | None) -> None:
    """Assert that a URL matches the contract's pattern with optional path parameters.

    Converts ``{placeholder}`` segments in the pattern to regex groups and checks
    that the URL path matches. When ``path_params`` is provided, also verifies that
    each placeholder was substituted with the expected value.
    """
    # Extract path from full URL
    path = url.split("?")[0]
    if "://" in path:
        # Strip scheme + host
        path = "/" + path.split("://", 1)[1].split("/", 1)[-1]

    # Build regex from pattern: {name} -> named group
    regex_pattern = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern)
    regex_pattern = f"^{regex_pattern}$"

    match = re.match(regex_pattern, path)
    assert match is not None, (
        f"URL path {path!r} does not match pattern {pattern!r} (regex: {regex_pattern!r})"
    )

    if path_params:
        for param_name, expected_value in path_params.items():
            actual = match.group(param_name)
            assert actual == expected_value, (
                f"Path param {param_name!r}: expected {expected_value!r}, got {actual!r}"
            )


def _check_auth_style(request: httpx.Request, contract: EndpointContract) -> None:
    """Assert the request uses the correct authentication style."""
    if contract.auth_style == "bearer":
        auth_header = request.headers.get("authorization", "")
        assert auth_header.lower().startswith("bearer "), (
            f"Expected Bearer auth, got Authorization: {auth_header!r}"
        )
    elif contract.auth_style == "basic":
        auth_header = request.headers.get("authorization", "")
        assert auth_header.startswith("Basic "), (
            f"Expected Basic auth, got Authorization: {auth_header!r}"
        )
    elif contract.auth_style == "query_params":
        url_str = str(request.url)
        assert "?" in url_str, "Expected query_params auth style but URL has no query string"


def _check_required_headers(request: httpx.Request, contract: EndpointContract) -> None:
    """Assert all required headers are present (values checked as prefix match for templates)."""
    for header_name, header_template in contract.required_headers.items():
        actual = request.headers.get(header_name.lower())
        assert actual is not None, f"Missing required header: {header_name!r}"

        # If the template contains {placeholders}, just check the static prefix
        if "{" in header_template:
            prefix = header_template.split("{")[0]
            assert actual.startswith(prefix), (
                f"Header {header_name!r}: expected prefix {prefix!r}, got {actual!r}"
            )
        else:
            assert actual == header_template, (
                f"Header {header_name!r}: expected {header_template!r}, got {actual!r}"
            )


def _validate_body_against_schema(body: dict[str, Any], schema: dict[str, object]) -> None:
    """Light-weight structural check: verify all required schema keys exist in body.

    This is NOT a full JSON Schema validator. It checks that every key defined in
    ``schema["properties"]`` (or every top-level key in the schema dict if no
    ``properties`` key) exists in the body. Nested schemas are checked recursively.
    """
    properties: dict[str, object] = schema.get("properties", schema)  # type: ignore[assignment]

    for key in properties:
        assert key in body, f"Missing required key {key!r} in body (have: {list(body.keys())})"
        prop_spec = properties[key]
        if isinstance(prop_spec, dict) and isinstance(body[key], dict):
            nested_props = prop_spec.get("properties") if "properties" in prop_spec else None
            if nested_props and isinstance(nested_props, dict):
                _validate_body_against_schema(body[key], prop_spec)


def assert_request_matches_contract(
    request: httpx.Request,
    contract: EndpointContract,
    path_params: dict[str, str] | None = None,
) -> None:
    """Assert that an httpx.Request conforms to the endpoint contract.

    Checks HTTP method, URL pattern match, required headers, authentication style,
    and request body schema (when the contract specifies one).

    Args:
        request: The captured httpx.Request to validate.
        contract: The endpoint contract to validate against.
        path_params: Optional mapping of path parameter names to expected values.

    Raises:
        AssertionError: When any contract constraint is violated.
    """
    # Method
    assert request.method.upper() == contract.method.upper(), (
        f"Expected method {contract.method}, got {request.method}"
    )

    # URL pattern
    _match_url_pattern(str(request.url), contract.url_pattern, path_params)

    # Required headers
    _check_required_headers(request, contract)

    # Auth style
    _check_auth_style(request, contract)

    # Request body schema
    if contract.request_schema is not None:
        import json

        body_bytes = request.content
        assert body_bytes, "Expected request body but got empty content"
        body = json.loads(body_bytes)
        _validate_body_against_schema(body, contract.request_schema)


def assert_response_parses(
    result: dict[str, Any] | list[Any] | str,
    contract: EndpointContract,
) -> None:
    """Assert that a tool's parsed response output matches the contract's response schema.

    For dict results, validates structure against ``contract.response_schema``.
    For string results, attempts JSON parse first. For list results, checks each
    element if the schema describes array items.

    Args:
        result: The parsed output from the MCP tool.
        contract: The endpoint contract defining the expected response shape.

    Raises:
        AssertionError: When the result does not match the response schema.
    """
    import json as json_mod

    # Normalize to dict for validation
    if isinstance(result, str):
        try:
            parsed = json_mod.loads(result)
        except (json_mod.JSONDecodeError, ValueError) as exc:
            msg = f"Result string is not valid JSON: {result[:200]!r}"
            raise AssertionError(msg) from exc
        if isinstance(parsed, dict):
            _validate_body_against_schema(parsed, contract.response_schema)
            return
        if isinstance(parsed, list):
            result = parsed
        else:
            return  # scalar — no structural check possible

    if isinstance(result, dict):
        _validate_body_against_schema(result, contract.response_schema)
    elif isinstance(result, list):
        # Check items schema if defined
        items_schema = contract.response_schema.get("items")
        if isinstance(items_schema, dict):
            for item in result:
                if isinstance(item, dict):
                    _validate_body_against_schema(item, items_schema)
