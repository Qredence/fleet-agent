"""Scripted mock runs replayed from the canonical NDJSON fixtures.

The fixtures in packages/contracts/fixtures are the shared golden streams:
this service parses them into typed AG-UI events, and the contract tests in
apps/api/tests keep them coherent with the AgentWorkspaceState schema.
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ag_ui.core import BaseEvent, Event, RunAgentInput, StateSnapshotEvent
from pydantic import TypeAdapter

from app.contracts.agent_state import AgentWorkspaceState
from app.services.run_input import last_user_text

_FIXTURES_DIR = (
    Path(__file__).resolve().parents[4] / "packages" / "contracts" / "fixtures"
)
_EVENT_ADAPTER: TypeAdapter[BaseEvent] = TypeAdapter(Event)


@dataclass(frozen=True)
class TimedEvent:
    """One fixture line: emit `event` `at_ms` after the stream starts."""

    at_ms: int
    event: BaseEvent


@lru_cache(maxsize=8)
def load_fixture(name: str) -> list[TimedEvent]:
    path = _FIXTURES_DIR / f"{name}.ndjson"
    if not path.is_file():
        raise RuntimeError(f"Unknown mock fixture: {name}")

    timed: list[TimedEvent] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            raw = json.loads(line)
            try:
                event = _EVENT_ADAPTER.validate_python(raw["event"])
            except Exception as exc:
                raise RuntimeError(
                    f"Invalid fixture event at {path}:{line_no}"
                ) from exc
            timed.append(TimedEvent(at_ms=int(raw["at"]), event=event))

    _validate_snapshots(name, timed)
    return timed


def _validate_snapshots(name: str, timed: list[TimedEvent]) -> None:
    """STATE_SNAPSHOT payloads must parse as AgentWorkspaceState."""
    del name  # fixture name only used by caller for error context
    for entry in timed:
        if isinstance(entry.event, StateSnapshotEvent):
            AgentWorkspaceState.model_validate(entry.event.snapshot, strict=False)


def select_fixture_name(input_data: RunAgentInput) -> str:
    """Deterministic mock routing so demo/error paths are reachable from the UI."""
    text = last_user_text(input_data).lower()
    if "no output" in text:
        return "forced-submit-run"
    if "tool error" in text:
        return "tool-error-run"
    return "successful-run"
