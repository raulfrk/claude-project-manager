"""Tests for server.lib._types — shared dataclasses and TypedDicts."""

from server.lib._types import (
    FeedbackResult,
    HookError,
    HookResultEntry,
    VerificationResult,
)


class TestVerificationResult:
    def test_instantiation(self):
        r = VerificationResult(hook_id="h1", status="pass", details="ok")
        assert r.hook_id == "h1"
        assert r.status == "pass"
        assert r.details == "ok"


class TestFeedbackResult:
    def test_instantiation(self):
        r = FeedbackResult(hook_id="h1", feedback_tool="fb", ok=True, error=None)
        assert r.ok is True
        assert r.error is None

    def test_with_error(self):
        r = FeedbackResult(hook_id="h1", feedback_tool="fb", ok=False, error="failed")
        assert r.ok is False
        assert r.error == "failed"


class TestHookError:
    def test_instantiation(self):
        e = HookError(hook_id="h1", error="timeout", target_tool="sync")
        assert e.error == "timeout"


class TestHookResultEntry:
    def test_instantiation(self):
        e = HookResultEntry(hook_id="h1", result='{"ok": true}', target_tool="sync")
        assert e.result == '{"ok": true}'

    def test_none_result(self):
        e = HookResultEntry(hook_id="h1", result=None, target_tool=None)
        assert e.result is None
