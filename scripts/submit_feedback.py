"""Stage 5.2 flywheel CLI -- record one piece of human feedback.

Captures a ``FeedbackEvent`` (bound to a trace) into the gitignored
``.local/feedback/`` store. When ``--result-json`` (a serialized
``AgentResult``) is given, the matching review candidates are also queued
(Rule A: negative feedback -> a USER_FEEDBACK candidate).

The demo requires a ``trace_id`` because Stage 5.2 binds every feedback to
the runtime trace it came from (spec §6/§7/§38).

Usage (from project root, inside .venv):

    python scripts/submit_feedback.py --trace-id tr_123 --query "..." --type INCOMPLETE
    python scripts/submit_feedback.py --trace-id tr_123 --query "..." --type BAD_CITATION \\
        --answer "30 分钟" --comment "need the exact section" --result-json out/result.json
"""

from __future__ import annotations

import asyncio
import json
import sys
from argparse import ArgumentParser
from pathlib import Path

from _flywheel_cli import PROJECT_ROOT, build_flywheel, load_env_file

from polaris_agentic_rag.agent.models import AgentResult
from polaris_agentic_rag.flywheel.models import (
    FeedbackType,
    is_negative_feedback,
)
from polaris_agentic_rag.flywheel.sanitizer import FeedbackSanitizer


async def main() -> int:
    parser = ArgumentParser(description="Record one feedback event into the flywheel.")
    parser.add_argument("--trace-id", required=True, help="Trace id this feedback refers to.")
    parser.add_argument("--query", required=True, help="The user query that was answered.")
    parser.add_argument("--type", required=True, choices=[t.value for t in FeedbackType])
    parser.add_argument("--answer", default="", help="The answer the user reacted to.")
    parser.add_argument("--comment", default=None, help="Optional free-text reviewer note.")
    parser.add_argument(
        "--result-json",
        type=Path,
        default=None,
        help="Optional serialized AgentResult to also queue review candidates from.",
    )
    parser.add_argument(
        "--no-redact",
        action="store_true",
        help="Skip the secret sanitizer (demo/debug only, not recommended).",
    )
    args = parser.parse_args()

    load_env_file(PROJECT_ROOT / ".env")

    feedback_type = FeedbackType(args.type)
    service = build_flywheel()

    event = await service.capture_feedback(
        trace_id=args.trace_id,
        query=args.query,
        answer=args.answer,
        feedback_type=feedback_type,
        comment=args.comment,
    )
    print(f"feedback            : {event.feedback_id}")
    print(f"trace_id            : {event.trace_id}")
    print(
        f"type                : {event.feedback_type.value} "
        f"({'reviewable' if is_negative_feedback(event.feedback_type) else 'positive'})"
    )

    if not is_negative_feedback(event.feedback_type):
        print("note                : positive feedback is acknowledged; no review candidate.")
        return 0

    #: queue review candidates from a supplied runtime result (Rule A/B/D/E)
    candidates = []
    if args.result_json is not None:
        if not args.result_json.is_file():
            print(f"error: result JSON not found: {args.result_json}", file=sys.stderr)
            return 2
        result = AgentResult(**json.loads(args.result_json.read_text(encoding="utf-8")))
        candidates = service.create_candidates(result, feedback=event)
        for c in candidates:
            print(f"candidate           : {c.candidate_id}  [{c.source.value}] {c.reason}")
    else:
        print(
            "note                : pass --result-json <AgentResult.json> to also queue "
            "review candidates (the flywheel needs a runtime Trace/AgentResult)."
        )

    if not args.no_redact:
        masked = FeedbackSanitizer().sanitize(event)
        changed = masked.model_dump() != event.model_dump()
        print(
            "secrets             : redacted on persist"
            if changed
            else "secrets             : none detected"
        )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
