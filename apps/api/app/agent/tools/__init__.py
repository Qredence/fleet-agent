"""Bundled tools for the DSPy engine.

Synchronous, typed, docstring-precise, and bounded (PR 6.4 in the plan):
ReActV2's loop executes them directly, so every network-facing tool would
own its timeouts. These two are local and deterministic — a docs search over
the bundled corpus and a clock.
"""

from app.agent.tools.corpus import CORPUS
from app.agent.tools.docs import get_current_time, search_docs

__all__ = ["CORPUS", "get_current_time", "search_docs"]
