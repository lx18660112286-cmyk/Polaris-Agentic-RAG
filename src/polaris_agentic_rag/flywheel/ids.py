"""ID + timestamp helpers for the data flywheel (spec §38/§39).

IDs are UUIDs (never a list index -- index is not a stable id, spec §38).
Timestamps are timezone-aware ISO-8601 UTC (spec §39).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TypeVar

T = TypeVar("T", bound=object)

__all__ = ["make_id", "utc_now_iso", "unique_append"]


def make_id(prefix: str) -> str:
    """Return a stable, unique id like ``<prefix>_<uuid-hex>``."""
    return f"{prefix}_{uuid.uuid4().hex}"


def utc_now_iso() -> str:
    """Return the current time as a timezone-aware ISO-8601 UTC string."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def unique_append(values: list[T], value: T) -> None:
    """Append ``value`` to ``values`` in place unless already present (identity)."""
    if value not in values:
        values.append(value)
