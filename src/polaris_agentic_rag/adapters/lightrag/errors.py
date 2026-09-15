"""Error taxonomy for the LightRAG adapter.

Stage 0 only defines the taxonomy skeleton; these errors will be raised
by the real adapter implementation in later stages. No exceptions are
raised by the source probe itself.
"""

from __future__ import annotations


class LightRAGAdapterError(Exception):
    """Base error for LightRAG adapter failures."""


class LightRAGImportError(LightRAGAdapterError):
    """LightRAG package/class is not importable or not discoverable."""


class LightRAGSourceError(LightRAGAdapterError):
    """LightRAG source checkout is missing or not usable."""


class LightRAGQueryError(LightRAGAdapterError):
    """A query against the LightRAG kernel failed."""


class LightRAGIngestError(LightRAGAdapterError):
    """Document ingestion into the LightRAG kernel failed."""


class LightRAGStorageError(LightRAGAdapterError):
    """Storage lifecycle operation failed."""
