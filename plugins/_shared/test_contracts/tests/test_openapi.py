"""Tests for openapi.py — loader, endpoint_contract, OpenAPISchemaValidator."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from test_contracts.openapi import (
    SpecError,
    _find_operation,
    _find_operation_by_path,
    endpoint_contract,
    is_manual_spec,
    list_operations,
    load,
    validator_for,
)


@pytest.fixture()
def sample_spec(tmp_path: Path) -> Path:
    """Write a minimal OpenAPI spec to a temp file and return its path."""
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Demo", "version": "1"},
        "paths": {
            "/widgets/{id}": {
                "get": {
                    "operationId": "getWidget",
                    "parameters": [
                        {
                            "name": "id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string"},
                        }
                    ],
                    "responses": {
                        "200": {
                            "description": "ok",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Widget"}
                                }
                            },
                        }
                    },
                },
                "delete": {
                    "operationId": "deleteWidget",
                    "responses": {"204": {"description": "no content"}},
                },
            },
            "/widgets": {
                "post": {
                    "operationId": "createWidget",
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {"schema": {"$ref": "#/components/schemas/Widget"}}
                        },
                    },
                    "responses": {
                        "201": {
                            "description": "created",
                            "content": {
                                "application/json": {
                                    "schema": {"$ref": "#/components/schemas/Widget"}
                                }
                            },
                        }
                    },
                }
            },
        },
        "components": {
            "schemas": {
                "Widget": {
                    "type": "object",
                    "required": ["id", "name"],
                    "properties": {
                        "id": {"type": "string"},
                        "name": {"type": "string"},
                        "count": {"type": "integer"},
                    },
                }
            }
        },
    }
    p = tmp_path / "demo.json"
    p.write_text(json.dumps(spec))
    return p


@pytest.fixture()
def manual_spec(tmp_path: Path) -> Path:
    spec = {
        "openapi": "3.1.0",
        "info": {"title": "Manual", "version": "1"},
        "x-cpm-source": "manual",
        "paths": {},
    }
    p = tmp_path / "manual.json"
    p.write_text(json.dumps(spec))
    return p


def test_load_reads_spec(sample_spec: Path) -> None:
    spec = load(sample_spec)
    assert spec["info"]["title"] == "Demo"


def test_find_operation_by_operation_id(sample_spec: Path) -> None:
    spec = load(sample_spec)
    url, method, op = _find_operation(spec, "getWidget")
    assert url == "/widgets/{id}"
    assert method == "GET"
    assert op["operationId"] == "getWidget"


def test_find_operation_missing_id(sample_spec: Path) -> None:
    spec = load(sample_spec)
    with pytest.raises(SpecError, match="nonesuch"):
        _find_operation(spec, "nonesuch")


def test_find_operation_by_path_missing(sample_spec: Path) -> None:
    spec = load(sample_spec)
    with pytest.raises(SpecError, match="path"):
        _find_operation_by_path(spec, "GET", "/missing")


def test_find_operation_by_path_wrong_method(sample_spec: Path) -> None:
    spec = load(sample_spec)
    with pytest.raises(SpecError, match=r"PATCH.*not defined"):
        _find_operation_by_path(spec, "PATCH", "/widgets/{id}")


def test_endpoint_contract_get(sample_spec: Path) -> None:
    c = endpoint_contract(sample_spec, "GET", "/widgets/{id}", auth_style="bearer")
    assert c.method == "GET"
    assert c.url_pattern == "/widgets/{id}"
    assert c.response_status == 200
    assert c.request_schema is None
    # response_schema has $ref pre-expanded to the resolved Widget schema.
    assert c.response_schema["type"] == "object"
    assert set(c.response_schema["required"]) == {"id", "name"}
    assert "name" in c.response_schema["properties"]


def test_endpoint_contract_post_with_request_body(sample_spec: Path) -> None:
    c = endpoint_contract(sample_spec, "POST", "/widgets", auth_style="bearer")
    assert c.method == "POST"
    assert c.response_status == 201
    assert c.request_schema is not None
    assert set(c.request_schema["required"]) == {"id", "name"}


def test_endpoint_contract_204_no_body(sample_spec: Path) -> None:
    c = endpoint_contract(sample_spec, "DELETE", "/widgets/{id}")
    assert c.response_status == 204
    assert c.response_schema == {}


def test_validator_accepts_conforming_body(sample_spec: Path) -> None:
    v = validator_for(sample_spec)
    schema = {"$ref": "#/components/schemas/Widget"}
    v.validate({"id": "w1", "name": "Foo"}, schema)  # required fields present


def test_validator_rejects_missing_required(sample_spec: Path) -> None:
    import jsonschema

    v = validator_for(sample_spec)
    schema = {"$ref": "#/components/schemas/Widget"}
    with pytest.raises(jsonschema.ValidationError):
        v.validate({"id": "w1"}, schema)  # missing `name`


def test_validator_is_valid_helper(sample_spec: Path) -> None:
    v = validator_for(sample_spec)
    schema = {"$ref": "#/components/schemas/Widget"}
    assert v.is_valid({"id": "w1", "name": "Foo"}, schema)
    assert not v.is_valid({"id": "w1"}, schema)


def test_list_operations(sample_spec: Path) -> None:
    spec = load(sample_spec)
    ops = list_operations(spec)
    ids = {op_id for op_id, _, _ in ops}
    assert ids == {"getWidget", "deleteWidget", "createWidget"}


def test_is_manual_spec(manual_spec: Path, sample_spec: Path) -> None:
    assert is_manual_spec(load(manual_spec)) is True
    assert is_manual_spec(load(sample_spec)) is False
