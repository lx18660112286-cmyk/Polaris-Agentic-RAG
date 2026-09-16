"""Basic secret redaction for persisted flywheel payloads (spec §40/§41).

The data flywheel starts storing long-lived user queries, so we add a
minimal ``FeedbackSanitizer`` that masks common secret-looking patterns
(``Authorization: Bearer ...``, ``DEEPSEEK_API_KEY=...``, ``api_key=...``,
sk-... provider keys) before anything hits the repository.

This is explicitly *basic redaction only* -- NOT a full DLP / retention /
PII system (spec §41/§43). Production would need real
retention/access-control/PII/deletion design.
"""

from __future__ import annotations

import re

from polaris_agentic_rag.flywheel.models import FeedbackEvent

__all__ = ["FeedbackSanitizer", "sanitize_text"]

_REDACTED = "<redacted:secret>"

#: Ordered (pattern, replacement) redaction rules (spec §41).
_SECRET_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(Authorization|authorization)\s*[:=]\s*Bearer\s+\S+"), f"{_REDACTED}"),
    (re.compile(r"(DEEPSEEK_API_KEY|DEEPSEEK_APP_KEY)\s*=\s*\S+"), f"{_REDACTED}"),
    (re.compile(r"\bapi_key\s*[=:]|=api-key|<api-key>"), f"{_REDACTED}"),
)

#: Whole-string heuristic fallback for stray provider keys.
_SK_KEY_RE = re.compile(r"^sk-[a-zA-Z0-9]{16,}$")


def sanitize_text(text: str | None) -> str:
    """Return ``text`` with common secret-looking patterns masked.

    ``None`` / empty input stays empty/unchanged. This is a best-effort
    redaction, not a complete DLP guarantee (spec §41).
    """
    if not text:
        return text or ""
    result = text
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    #: whole-value provider key fallback (e.g. a pasted sk-... value)
    if _SK_KEY_RE.match(result.strip()):
        result = _REDACTED
    return result


class FeedbackSanitizer:
    """Applies :func:`sanitize_text` to every persisted field of a FeedbackEvent."""

    def sanitize(self, event: FeedbackEvent) -> FeedbackEvent:
        """Return a copy of ``event`` with secret-looking text masked."""
        return event.model_copy(
            update={
                "query": sanitize_text(event.query),
                "answer": sanitize_text(event.answer),
                "comment": sanitize_text(event.comment or "") or None,
                "citations": [sanitize_text(c) for c in event.citations],
            }
        )
