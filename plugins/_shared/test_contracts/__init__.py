"""Shared test contract infrastructure for API endpoint testing."""

from test_contracts.base import EndpointContract, ErrorContract
from test_contracts.builders import (
    build_error_response,
    build_paginated_response,
    build_success_response,
)
from test_contracts.fixtures import (
    discover_get_client_locations,
    patch_get_client_everywhere,
    setattr_get_client_everywhere,
)
from test_contracts.openapi import (
    OpenAPISchemaValidator,
    SpecError,
    endpoint_contract,
    is_manual_spec,
    list_operations,
    load,
    validator_for,
)
from test_contracts.validators import (
    assert_request_matches_contract,
    assert_response_parses,
)

__all__ = [
    "EndpointContract",
    "ErrorContract",
    "OpenAPISchemaValidator",
    "SpecError",
    "assert_request_matches_contract",
    "assert_response_parses",
    "build_error_response",
    "build_paginated_response",
    "build_success_response",
    "discover_get_client_locations",
    "endpoint_contract",
    "is_manual_spec",
    "list_operations",
    "load",
    "patch_get_client_everywhere",
    "setattr_get_client_everywhere",
    "validator_for",
]
