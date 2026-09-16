"""Stage 5.2 flywheel CLI -- print the data-flywheel report (spec §55).

Aggregates feedback / review-queue / proposal / eval-candidate counters and
prints a simple, honest report. The ``--scope`` text is surfaced so demo
data is never presented as production metrics (spec §55).

Usage (from project root, inside .venv):

    python scripts/flywheel_report.py
    python scripts/flywheel_report.py --dataset examples/evaluation/dev_knowledge_eval.jsonl
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser
from pathlib import Path

from _flywheel_cli import PROJECT_ROOT, build_flywheel, load_env_file


def main() -> int:
    parser = ArgumentParser(description="Print the data-flywheel report.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=None,
        help="Evaluation dataset path to mention in the report (optional).",
    )
    parser.add_argument(
        "--scope",
        default="development/demo data",
        help="Scope label surfaced so demo data is not mistaken for production.",
    )
    args = parser.parse_args()

    load_env_file(PROJECT_ROOT / ".env")
    service = build_flywheel()
    print(service.report(dataset_path=str(args.dataset) if args.dataset else "", scope=args.scope))
    return 0


if __name__ == "__main__":
    sys.exit(main())
