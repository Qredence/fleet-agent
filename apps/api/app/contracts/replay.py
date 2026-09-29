"""The typed shape of one canonical fixture line.

Each line in ``packages/contracts/fixtures/*.ndjson`` is
``{"at": <ms>, "event": <AG-UI event>}``. Fixture-replay infrastructure
parses them into :class:`TimedEvent`; the AG-UI coordinators consume them.
"""

from __future__ import annotations

from dataclasses import dataclass

from ag_ui.core import BaseEvent


@dataclass(frozen=True)
class TimedEvent:
    """One fixture line: emit `event` `at_ms` after the stream starts."""

    at_ms: int
    event: BaseEvent
