"""Tests for native DSPy callback bridging (AgUiRunCallback)."""

import asyncio
from typing import Any

import dspy

from app.agent.callbacks import AgUiRunCallback
from app.agent.signature import AgentSignature
from app.agent.tools.docs import SearchDocsTool
from app.agui.cancel_token import RunCancelToken
from app.agui.event_bus import DONE, RunEventBus
from app.contracts.domain import (
    InlineDataEvent,
    SourceDiscovered,
    SourceResult,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)
from tests.helpers.scripted_lm import ScriptedLM, submit_call


async def _drain_bus(bus: RunEventBus) -> list[Any]:
    bus.close_from_loop()
    events = []
    while True:
        event = await bus.next()
        if event is DONE:
            break
        events.append(event)
    return events


async def test_callback_publishes_tool_started_and_completed():
    loop = asyncio.get_running_loop()
    bus = RunEventBus(loop)
    callback = AgUiRunCallback(bus)

    def simple_tool(query: str) -> str:
        """A simple search tool."""
        return f"result for {query}"

    lm = ScriptedLM(
        [
            [{"name": "simple_tool", "args": {"query": "dspy"}}],
            [submit_call(answer="finished")],
        ]
    )
    agent = dspy.ReActV2(AgentSignature, tools=[simple_tool], max_iters=2)

    def run_sync() -> dspy.Prediction:
        with dspy.context(
            lm=lm,
            adapter=dspy.JSONAdapter(use_native_function_calling=True),
            callbacks=[callback],
        ):
            return agent(user_request="search dspy")

    pred = await asyncio.to_thread(run_sync)
    assert pred.answer == "finished"

    events = await _drain_bus(bus)
    assert len(events) == 2
    started, completed = events
    assert isinstance(started, ToolStarted)
    assert started.name == "simple_tool"
    assert "dspy" in started.input_preview
    assert isinstance(completed, ToolCompleted)
    assert completed.name == "simple_tool"
    assert "result for dspy" in completed.output_preview
    assert completed.tool_call_id == started.tool_call_id


async def test_callback_publishes_tool_failed_on_exception():
    loop = asyncio.get_running_loop()
    bus = RunEventBus(loop)
    callback = AgUiRunCallback(bus)

    def error_tool(query: str) -> str:
        """A tool that raises."""
        raise RuntimeError("database crash")

    lm = ScriptedLM(
        [
            [{"name": "error_tool", "args": {"query": "fail"}}],
            [submit_call(answer="recovered after failure")],
        ]
    )
    agent = dspy.ReActV2(AgentSignature, tools=[error_tool], max_iters=2)

    def run_sync() -> dspy.Prediction:
        with dspy.context(
            lm=lm,
            adapter=dspy.JSONAdapter(use_native_function_calling=True),
            callbacks=[callback],
        ):
            return agent(user_request="test error")

    pred = await asyncio.to_thread(run_sync)
    assert pred.answer == "recovered after failure"

    events = await _drain_bus(bus)
    assert len(events) == 2
    started, failed = events
    assert isinstance(started, ToolStarted)
    assert isinstance(failed, ToolFailed)
    assert failed.name == "error_tool"
    assert failed.error_message == "The error_tool tool call failed."


async def test_callback_emits_source_discovered():
    loop = asyncio.get_running_loop()
    bus = RunEventBus(loop)
    callback = AgUiRunCallback(bus)
    docs_tool = SearchDocsTool()

    lm = ScriptedLM(
        [
            [{"name": "search_docs", "args": {"query": "ag-ui"}}],
            [submit_call(answer="found docs")],
        ]
    )
    agent = dspy.ReActV2(AgentSignature, tools=[docs_tool], max_iters=2)

    def run_sync() -> dspy.Prediction:
        with dspy.context(
            lm=lm,
            adapter=dspy.JSONAdapter(use_native_function_calling=True),
            callbacks=[callback],
        ):
            return agent(user_request="query docs")

    pred = await asyncio.to_thread(run_sync)
    assert pred.answer == "found docs"

    events = await _drain_bus(bus)
    started = [e for e in events if isinstance(e, ToolStarted)]
    completed = [e for e in events if isinstance(e, ToolCompleted)]
    sources = [e for e in events if isinstance(e, SourceDiscovered)]

    assert len(started) == 1
    assert len(completed) == 1
    assert len(sources) > 0
    assert sources[0].tool_call_id == started[0].tool_call_id


async def test_callback_respects_cancel_token():
    loop = asyncio.get_running_loop()
    bus = RunEventBus(loop)
    cancel_token = RunCancelToken()
    callback = AgUiRunCallback(bus, cancel_token=cancel_token)

    cancel_token.cancel()

    def blocked_tool(query: str) -> str:
        return "result"

    lm = ScriptedLM(
        [
            [{"name": "blocked_tool", "args": {"query": "test"}}],
            [submit_call(answer="done")],
        ]
    )
    agent = dspy.ReActV2(AgentSignature, tools=[blocked_tool], max_iters=2)

    def run_sync() -> dspy.Prediction:
        with dspy.context(
            lm=lm,
            adapter=dspy.JSONAdapter(use_native_function_calling=True),
            callbacks=[callback],
        ):
            return agent(user_request="should cancel")

    pred = await asyncio.to_thread(run_sync)
    assert pred.answer == "done"

    events = await _drain_bus(bus)
    # When cancelled, no tool started/completed events should be published to the bus
    assert len(events) == 0


async def test_callback_emits_bounded_web_search_and_source_projections():
    loop = asyncio.get_running_loop()
    bus = RunEventBus(loop)
    callback = AgUiRunCallback(bus)

    class WebSearch:
        __name__ = "web_search"

        def __init__(self) -> None:
            self.__name__ = "web_search"
            self.last_sources = [
                SourceResult(
                    id="w1",
                    title="Official docs",
                    source_type="web",
                    uri="https://example.com/path",
                    excerpt="private excerpt stays out of the inline card",
                )
            ]

    tool = WebSearch()
    callback.on_tool_start(
        "call-1",
        tool,
        {"kwargs": {"query": "latest DSPy behavior", "token": "secret"}},
    )
    callback.on_tool_end("call-1", "bounded result")
    await asyncio.sleep(0)

    events = await _drain_bus(bus)
    web_events = [
        event
        for event in events
        if isinstance(event, InlineDataEvent) and event.name == "web-search"
    ]
    source_events = [
        event
        for event in events
        if isinstance(event, InlineDataEvent) and event.name == "sources"
    ]
    assert len(web_events) == 2
    assert len(source_events) == 1
    assert web_events[0].value["searching"] is True
    assert web_events[1].value["searching"] is False
    assert web_events[1].value["results"] == [
        {"title": "Official docs", "domain": "example.com"}
    ]
    assert source_events[0].value == {
        "schemaVersion": 1,
        "sources": [{"title": "Official docs", "domain": "example.com"}],
    }
    assert "secret" not in str(web_events[0].value)
