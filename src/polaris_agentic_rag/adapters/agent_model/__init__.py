"""Agent Model provider adapters.

This is the ONLY package allowed to import provider SDKs (``openai``) for
the agent loop. It translates our provider-neutral agent types to/from the
provider wire format. ``AgentOrchestrator`` never imports these.
"""

from __future__ import annotations
