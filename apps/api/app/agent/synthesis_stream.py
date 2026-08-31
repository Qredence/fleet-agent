"""DSPy-native synthesis streaming seam.

The engine streams the synthesis predictor's public fields through
``dspy.streamify`` + ``StreamListener``.  This module holds the one piece of
DSPy-specific wiring that exists outside the engine boundary: the listener
subclass that keeps stream-chunk parsing aligned with the adapter the
synthesis call actually used.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

import dspy
from dspy.streaming import StreamListener

if TYPE_CHECKING:
    from litellm import ModelResponseStream


class SynthesisStreamListener(StreamListener):  # type: ignore[misc]
    """StreamListener pinned to ChatAdapter field boundaries.

    The synthesis call runs under a scoped ``dspy.context(adapter=ChatAdapter())``
    inside the program's worker thread (ChatAdapter's ``[[ ## field ## ]]``
    sections give exact, boilerplate-free boundaries).  The stream consumer
    task that calls ``receive`` runs on the event loop and cannot see that
    thread-local scope, so the adapter is pinned here explicitly: otherwise
    the listener would parse ChatAdapter sections with the ambient
    JSONAdapter's identifiers and never detect a field boundary.
    """

    def receive(self, chunk: ModelResponseStream) -> Any:
        with dspy.context(adapter=dspy.ChatAdapter()):
            return super().receive(chunk)


def synthesis_stream_listeners(fields: Sequence[str]) -> list[SynthesisStreamListener]:
    """Build one pinned listener per synthesis output field."""
    return [SynthesisStreamListener(signature_field_name=field) for field in fields]
