"""Stage 5.2 flywheel CLI -- promote a labeled eval candidate into the dataset.

Explicit human promotion (spec §24): takes a PENDING ``EvalCandidate``
(previously created via ``review_feedback.py propose``), de-duplicates it
against the currently-loaded dataset cases (normalized query match, spec
§26), and marks it PROMOTED. The flywheel only *marks* the candidate --
it never auto-appends to the dataset file; the human copies the produced
``EvalCase`` into the dataset when they are ready.

Subcommands:

    list                     show pending eval candidates
    promote <id> --dataset   de-dup + promote a candidate against the dataset

Usage (from project root, inside .venv):

    python scripts/promote_eval_case.py list
    python scripts/promote_eval_case.py promote <id> \\
        --dataset examples/evaluation/dev_knowledge_eval.jsonl
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser, Namespace

from _flywheel_cli import PROJECT_ROOT, build_flywheel, load_env_file

from polaris_agentic_rag.evaluation.runner import load_dataset
from polaris_agentic_rag.flywheel.service import DataFlywheelService


def _list(service: DataFlywheelService, _args: Namespace) -> int:
    candidates = service.list_eval_candidates()
    if not candidates:
        print("no eval candidates")
        return 0
    for c in candidates:
        if c.category:
            print(f"  {c.candidate_id}  [{c.status.value:8s}] {c.category:20s} {c.query}")
        else:
            print(f"  {c.candidate_id}  [{c.status.value:8s}] {c.query}")
    return 0


def _promote(service: DataFlywheelService, args: Namespace) -> int:
    dataset_path = args.dataset.resolve()
    if not dataset_path.is_file():
        print(f"error: dataset not found: {dataset_path}", file=sys.stderr)
        return 2
    cases = load_dataset(dataset_path)
    print(f"dataset cases       : {len(cases)}")

    result = service.promote_eval_candidate(args.candidate_id, dataset_cases=cases)
    print(f"result              : {'PROMOTED' if result.promoted else 'NOT PROMOTED'}")
    print(f"reason              : {result.reason}")
    if result.promoted and result.eval_case is not None:
        ec = result.eval_case
        print(f"eval_case id        : {ec.id}")
        print(f"eval_case query     : {ec.query}")
        print(f"should_call_tool    : {ec.should_call_tool}")
        print("action              : copy this EvalCase into the dataset file to persist it.")
    return 0 if result.promoted else 0


async def main() -> int:
    parser = ArgumentParser(description="Promote labeled eval candidates into the dataset.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List eval candidates.")
    p_list.set_defaults(func=_list)

    p_promote = sub.add_parser("promote", help="De-dup + promote one candidate.")
    p_promote.add_argument("candidate_id")
    p_promote.add_argument("--dataset", required=True, help="Path to the evaluation dataset JSONL.")
    p_promote.set_defaults(func=_promote)

    args = parser.parse_args()
    load_env_file(PROJECT_ROOT / ".env")
    service = build_flywheel()
    return int(args.func(service, args))


if __name__ == "__main__":
    import asyncio

    sys.exit(asyncio.run(main()))
