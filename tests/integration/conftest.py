"""Load local environment for integration tests without sharing secrets.

Reads the gitignored project ``.env`` file (if present) into the process
environment so ``os.environ`` lookups in the adapter harness work.
"""

from __future__ import annotations

from pathlib import Path

try:  # python-dotenv ships with LightRAG deps
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - dev tooling only

    def load_dotenv(*_args: object, **_kwargs: object) -> bool:  # type: ignore[misc]
        return False


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def pytest_configure(config: object) -> None:
    """Hook called by pytest after config init."""
    load_dotenv(PROJECT_ROOT / ".env")
