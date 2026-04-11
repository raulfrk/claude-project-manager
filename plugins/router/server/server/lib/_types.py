"""Shared type definitions for the hooks plugin."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TypedDict

# Recursive JSON value type — for genuinely variable JSON/YAML data where
# the schema is user-defined or comes from external sources (parsed JSON
# payloads, YAML config, template mapping values).
JsonValue = str | int | float | bool | None | dict[str, "JsonValue"] | list["JsonValue"]


# ── Dataclasses for reusable structured results ─────────────────────────────


@dataclass(slots=True)
class VerificationResult:
    """Per-hook result from a verification phase."""

    hook_id: str
    status: str
    details: str


@dataclass(slots=True)
class FeedbackResult:
    """Result of a feedback writeback for a blocking hook."""

    hook_id: str
    feedback_tool: str
    ok: bool
    error: str | None


@dataclass(slots=True)
class HookError:
    """Error detail from a failed hook fire."""

    hook_id: str
    error: str
    target_tool: str


@dataclass(slots=True)
class HookResultEntry:
    """A single blocking hook result in the fire summary."""

    hook_id: str
    result: str | None
    target_tool: str | None


# ── TypedDicts for YAML/JSON serialization boundaries ────────────────────────


class FailureEntry(TypedDict, total=False):
    """A single failure log entry in hooks-failures.yaml."""

    timestamp: str
    hook_id: str
    trigger_tool: str
    target_tool: str
    server: str
    error: str
    retry_count: int
    source_result: str


class VerificationEntry(TypedDict):
    """A single verification log entry in hooks-verifications.yaml."""

    timestamp: str
    trigger_tool: str
    hook_id: str
    status: str
    details: str


class InvocationEntry(TypedDict, total=False):
    """A single invocation log entry in hooks-invocations.yaml."""

    timestamp: str
    hook_id: str
    trigger_tool: str
    target_tool: str
    server: str
    source_result: str
    payload: str


class FireSummary(TypedDict, total=False):
    """Summary dict returned by _fire_hooks_internal — serialized via json.dumps."""

    hooks_fired: int
    skipped: int
    errors: list[dict[str, str]]
    results: list[dict[str, str | None]]
    depth: int
    max_depth: int
    non_blocking_dispatched: int
    top_level: bool
    verification: list[dict[str, str]]
    feedback: list[dict[str, str | bool | None]]
    cascade_errors: list[str]
    depth_limited: bool
    message: str
