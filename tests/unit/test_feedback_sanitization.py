"""Offline tests for FeedbackSanitizer + secret redaction (spec §40/§41).

The flywheel applies *basic* redaction only (explicitly NOT full DLP /
PII masking -- spec §41/§43). These tests assert the exact documented
patterns: ``Authorization: Bearer``, ``DEEPSEEK_API_KEY=`` / api_key
fields, and a whole-string ``sk-...`` value. Inline keys inside otherwise
normal sentences are deliberately out of scope for the fallback.
"""

from __future__ import annotations

from polaris_agentic_rag.flywheel.models import FeedbackEvent, FeedbackType
from polaris_agentic_rag.flywheel.sanitizer import FeedbackSanitizer, sanitize_text


def test_sanitize_bearer_authorization_header() -> None:
    out = sanitize_text("Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz rest")
    assert "<redacted:secret>" in out
    assert "sk-" not in out


def test_sanitize_deepseek_key_env() -> None:
    out = sanitize_text("DEEPSEEK_API_KEY=sk-1234567890abcdef deadbeef")
    assert "<redacted:secret>" in out
    assert "sk-1234567890abcdef" not in out


def test_sanitize_api_key_field() -> None:
    out = sanitize_text("api_key = sk-abcdef1234567890")
    assert "<redacted:secret>" in out


def test_sanitize_whole_string_provider_key() -> None:
    assert sanitize_text("sk-abcdefghijklmnopqrstuvwxyz123456") == "<redacted:secret>"


def test_sanitize_leaves_plain_text() -> None:
    text = "Why is the access token valid for 30 minutes?"
    assert sanitize_text(text) == text


def test_sanitize_none_and_empty() -> None:
    assert sanitize_text(None) == ""
    assert sanitize_text("") == ""


def test_feedback_sanitizer_masks_redactable_fields() -> None:
    event = FeedbackEvent(
        feedback_id="fb1",
        trace_id="t1",
        query="Authorization: Bearer sk-abcdefghijklmnopqrstuvwxyz a=b",
        answer="DEEPSEEK_API_KEY=sk-1234567890abcdef deadbeef",
        comment="",
        citations=["plain note"],
        feedback_type=FeedbackType.OTHER,
    )
    clean = FeedbackSanitizer().sanitize(event)
    assert "<redacted:secret>" in clean.query
    assert "<redacted:secret>" in clean.answer
    #: original object is never mutated (returns a copy)
    assert event.query.startswith("Authorization: Bearer sk-")
