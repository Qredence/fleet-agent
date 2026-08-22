import asyncio

import pytest

from app.agent.instrumented import (
    instrument_tool,
    preview,
    sanitize_args,
    truncate_result,
)
from app.agui.event_bus import DONE, RunEventBus
from app.contracts.domain import ToolCompleted, ToolFailed, ToolStarted


def test_sanitize_args_redacts_secret_looking_values():
    result = sanitize_args(
        {
            "query": "openai setup",
            "api_key": "sk-secret-value",
            "authToken": "bearer abc",
            "password": "hunter2",
        }
    )
    assert "sk-secret-value" not in result
    assert "bearer abc" not in result
    assert "hunter2" not in result
    assert result.count('"***"') == 3
    assert "openai setup" in result


def test_sanitize_args_caps_values_and_total():
    result = sanitize_args({"query": "x" * 1000})
    assert len(result) <= 401


def test_preview_and_truncate_bounds():
    assert len(preview("y" * 1000)) <= 301
    assert len(truncate_result("y" * 5000)) <= 2001
    assert preview("  short  ") == "short"


async def _collect(bus: RunEventBus, count: int) -> list:
    out = []
    for _ in range(count):
        out.append(await bus.next())
    return out


async def test_instrument_tool_publishes_events_and_preserves_return():
    loop = asyncio.get_running_loop()
    bus = RunEventBus(loop)

    def lookup(query: str, limit: int = 3) -> str:
        """Look up docs."""
        return f"docs for {query}"

    wrapped = instrument_tool(lookup, bus)
    assert wrapped.__name__ == "lookup"
    assert "Look up docs." in (wrapped.__doc__ or "")

    result = wrapped(query="state deltas", limit=5)
    assert result == "docs for state deltas"

    started, completed = await _collect(bus, 2)
    assert isinstance(started, ToolStarted)
    assert isinstance(completed, ToolCompleted)
    assert started.tool_call_id == completed.tool_call_id
    assert started.name == "lookup"
    assert (
        '"state deltas"' in started.input_preview
        or "state deltas" in started.input_preview
    )
    assert "docs for state deltas" in completed.output_preview
    assert completed.duration_ms >= 0


async def test_instrument_tool_failure_is_public_and_reraises():
    loop = asyncio.get_running_loop()
    bus = RunEventBus(loop)

    def exploding(provider_key: str) -> str:
        """Boom."""
        raise RuntimeError(f"provider key {provider_key} rejected")

    wrapped = instrument_tool(exploding, bus)
    with pytest.raises(RuntimeError, match="provider key"):
        wrapped(provider_key="sk-nope")

    started, failed = await _collect(bus, 2)
    assert isinstance(started, ToolStarted)
    assert isinstance(failed, ToolFailed)
    assert failed.tool_call_id == started.tool_call_id
    # Secret never reaches the public event payload.
    assert "sk-nope" not in failed.error_message
    assert "sk-nope" not in started.input_preview
    assert failed.error_message == "The exploding tool call failed."


async def test_bus_closes_with_sentinel_after_close():
    loop = asyncio.get_running_loop()
    bus = RunEventBus(loop)
    bus.close_from_loop()
    assert (await bus.next()) is DONE
