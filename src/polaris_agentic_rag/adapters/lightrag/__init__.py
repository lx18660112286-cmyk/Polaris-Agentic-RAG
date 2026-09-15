"""LightRAG adapter package.

This is the ONLY package allowed to import LightRAG in production code.

Stage 0 scope:
- configuration skeleton (``settings.py``)
- error taxonomy (``errors.py``)
- source probe / runtime introspection (``source_probe.py``)

No RAG business logic is implemented in Stage 0.
"""

__all__: list[str] = []
