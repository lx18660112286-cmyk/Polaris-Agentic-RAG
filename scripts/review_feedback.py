"""Stage 5.2 flywheel CLI -- manual review queue + proposal creation.

A human reviews queued ``ReviewCandidate`` records and, for accepted ones,
creates (and auto-accepts) an ``ImprovementProposal`` -- then materializes
a labeled ``EvalCandidate`` ready for a later ``promote_eval_case.py``.

Subcommands:

    list                     show pending candidates
    review  <id> --decision  mark a candidate ACCEPTED/REJECTED/NO_ACTION
    propose <id> --category  accept + create ADD_EVAL_CASE proposal, then
                             make the corresponding EvalCandidate

Human review is the mandatory gate (spec §19): nothing here edits the
router, prompt, or knowledge base -- it only records data-state transitions.

Usage (from project root, inside .venv):

    python scripts/review_feedback.py list
    python scripts/review_feedback.py review <id> --decision ACCEPTED --category KNOWLEDGE_GAP
    python scripts/review_feedback.py propose <id> --category KNOWLEDGE_GAP
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace

from _flywheel_cli import PROJECT_ROOT, build_flywheel, load_env_file

from polaris_agentic_rag.flywheel.models import (
    ImprovementCategory,
    ProposalType,
    ReviewStatus,
)
from polaris_agentic_rag.flywheel.service import DataFlywheelService


def _list(service: DataFlywheelService, args: Namespace) -> int:
    from polaris_agentic_rag.flywheel.models import ReviewStatus

    status = ReviewStatus(args.status) if args.status else ReviewStatus.PENDING
    cands = service._queue.list_all(status=status)  # noqa: SLF001 - demo inspects queue
    if not cands:
        print(f"no review candidates with status={status.value}")
        return 0
    for c in cands:
        print(
            f"  {c.candidate_id}  {c.source.value:18s} {c.priority.value:8s} "
            f"[category={c.category.value if c.category else '-'}]  {c.reason}"
        )
    return 0


def _review(service: DataFlywheelService, args: Namespace) -> int:
    category = ImprovementCategory(args.category) if args.category else None
    updated = service.review_candidate(
        args.candidate_id,
        decision=ReviewStatus(args.decision),
        category=category,
        notes=args.notes,
        reviewed_by="cli",
    )
    if updated is None:
        print(f"candidate not found: {args.candidate_id}", file=sys.stderr)
        return 2
    cat = f"category={updated.category.value}" if updated.category else "category=unset"
    print(f"reviewed {updated.candidate_id}: status={updated.status.value}  {cat}")
    return 0


def _propose(service: DataFlywheelService, args: Namespace) -> int:
    category = ImprovementCategory(args.category)
    #: review must conclude ACCEPTED before a proposal can be created
    reviewed = service.review_candidate(
        args.candidate_id,
        decision=ReviewStatus.ACCEPTED,
        category=category,
        reviewed_by="cli",
    )
    if reviewed is None:
        print(f"candidate not found: {args.candidate_id}", file=sys.stderr)
        return 2

    proposal = service.create_proposal(
        [args.candidate_id],
        proposal_type=ProposalType.ADD_EVAL_CASE,
        category=category,
        title=args.title,
    )
    if proposal is None:
        print("error: could not create proposal", file=sys.stderr)
        return 2
    service.accept_proposal(proposal.proposal_id)

    evc = service.create_eval_candidate(
        proposal_id=proposal.proposal_id,
        candidate_id=args.candidate_id,
        query=reviewed.query,
        category=reviewed.category.value if reviewed.category else "",
        should_retrieve=True,
    )
    print(f"candidate           : {args.candidate_id}  -> ACCEPTED")
    print(f"proposal            : {proposal.proposal_id}  -> {proposal.status.value}")
    print(f"proposal_type       : {proposal.proposal_type.value}")
    print(
        f"eval_candidate      : {evc.candidate_id if evc else 'NONE (complete the label manually)'}"
    )
    if evc is None:
        print("error: eval candidate not created", file=sys.stderr)
        return 2
    print(f"next                : python scripts/promote_eval_case.py promote {evc.candidate_id}")
    return 0


async def main() -> int:
    parser = ArgumentParser(description="Review flywheel candidates + create proposals.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List review candidates.")
    p_list.add_argument("--status", default=None, help="Filter (default PENDING).")
    p_list.set_defaults(func=_list)

    p_review = sub.add_parser("review", help="Mark one candidate reviewed.")
    p_review.add_argument("candidate_id")
    p_review.add_argument("--decision", required=True, choices=[s.value for s in ReviewStatus])
    p_review.add_argument(
        "--category", default=None, choices=[c.value for c in ImprovementCategory]
    )
    p_review.add_argument("--notes", default="")
    p_review.set_defaults(func=_review)

    p_propose = sub.add_parser(
        "propose", help="Accept a candidate and create an eval-case proposal."
    )
    p_propose.add_argument("candidate_id")
    p_propose.add_argument(
        "--category", required=True, choices=[c.value for c in ImprovementCategory]
    )
    p_propose.add_argument("--title", default="")
    p_propose.set_defaults(func=_propose)

    args = parser.parse_args()
    load_env_file(PROJECT_ROOT / ".env")
    service = build_flywheel()
    return int(args.func(service, args))


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
