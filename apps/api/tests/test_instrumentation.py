"""Public tool-event redaction and the seam that publishes it.

Tool lifecycle events come from ``AgUiRunCallback`` (DSPy's BaseCallback seam);
the ``instrumented`` module holds only the pure redaction helpers it calls. These
tests drive the callback directly, which is what the engine installs on a run.
"""

import asyncio
import json

import pytest

from app.agent.callbacks import AgUiRunCallback
from app.agent.event_bus import DONE, RunEventBus
from app.agent.instrumented import preview, public_tool_args_json, truncate_result
from app.contracts.domain import ToolCompleted, ToolFailed, ToolStarted


def test_public_mutating_args_are_bounded_but_valid_json():
    encoded = public_tool_args_json(
        "write",
        {"path": "notes.md", "content": "x" * 5000},
    )
    public = json.loads(encoded)

    assert public["path"] == {"type": "string", "chars": 8}
    assert public["content"]["chars"] == 5000
    assert "preview" not in public["content"]
    assert "x" * 5000 not in encoded


def test_public_args_redact_secret_looking_values():
    encoded = public_tool_args_json(
        "lookup",
        {
            "query": "openai setup",
            "api_key": "sk-secret-value",
            "authToken": "bearer abc",
            "password": "hunter2",
        },
    )
    assert "sk-secret-value" not in encoded
    assert "bearer abc" not in encoded
    assert "hunter2" not in encoded
    assert json.loads(encoded)["query"] == {"type": "string", "chars": 12}


def test_public_args_convert_non_finite_numbers_to_valid_json():
    encoded = public_tool_args_json("lookup", {"score": float("nan")})

    assert json.loads(encoded)["score"] == {"type": "number", "finite": False}


def test_public_args_preserve_finite_numbers():
    encoded = public_tool_args_json("lookup", {"score": 0.75})

    assert json.loads(encoded)["score"] == 0.75


def test_preview_and_truncate_bounds():
    assert len(preview("y" * 1000)) <= 301
    assert len(truncate_result("y" * 5000)) <= 2001
    assert preview("  short  ") == "short"


async def _collect(bus: RunEventBus, count: int) -> list:
    return [await bus.next() for _ in range(count)]


async def test_callback_publishes_tool_events_and_keeps_the_real_result():
    bus = RunEventBus(asyncio.get_running_loop())
    callback = AgUiRunCallback(bus=bus)

    def lookup(query: str, limit: int = 3) -> str:
        """Look up docs."""
        return f"docs for {query}"

    result = lookup(query="state deltas", limit=5)
    assert result == "docs for state deltas"

    callback.on_tool_start(
        "call-1", lookup, {"kwargs": {"query": "state deltas", "limit": 5}}
    )
    callback.on_tool_end("call-1", result)

    started, completed = await _collect(bus, 2)
    assert isinstance(started, ToolStarted)
    assert isinstance(completed, ToolCompleted)
    assert started.tool_call_id == completed.tool_call_id
    assert started.name == "lookup"
    assert json.loads(started.arguments_json)["query"] == {
        "type": "string",
        "chars": 12,
    }
    assert "docs for state deltas" in completed.output_preview
    assert completed.duration_ms >= 0


async def test_callback_failure_is_public_and_scrubbed():
    bus = RunEventBus(asyncio.get_running_loop())
    callback = AgUiRunCallback(bus=bus)

    def exploding(provider_key: str) -> str:
        """Boom."""
        raise RuntimeError(f"provider key {provider_key} rejected")

    with pytest.raises(RuntimeError, match="provider key"):
        exploding(provider_key="sk-nope")

    callback.on_tool_start("call-1", exploding, {"kwargs": {"provider_key": "sk-nope"}})
    callback.on_tool_end("call-1", None, RuntimeError("provider key sk-nope rejected"))

    started, failed = await _collect(bus, 2)
    assert isinstance(started, ToolStarted)
    assert isinstance(failed, ToolFailed)
    assert failed.tool_call_id == started.tool_call_id
    # Secret never reaches the public event payload.
    assert "sk-nope" not in failed.error_message
    assert "sk-nope" not in started.input_preview
    assert failed.error_message == "The exploding tool call failed."


async def test_bus_closes_with_sentinel_after_close():
    bus = RunEventBus(asyncio.get_running_loop())
    bus.close_from_loop()
    assert (await bus.next()) is DONE
