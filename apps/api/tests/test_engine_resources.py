"""Run-owned clients close after work unwinds, on every terminal path."""

import asyncio
import threading

import dspy
import pytest

from app.agent.engine import AgentRunContext, DspyAgentEngine
from app.agent.event_bus import RunEventBus
from app.agent.factory import make_engine_builder
from app.services.artifact_storage import LocalArtifactStorage
from app.settings import Settings
from tests.helpers.scripted_lm import ScriptedLM, StreamingScriptedLM, synthesis_call

CTX = AgentRunContext(thread_id="fixture", run_id="fixture")


@pytest.mark.parametrize("streaming", [False, True])
async def test_program_factory_failure_closes_resources(streaming):
    closed = []

    def broken():
        raise ValueError("fixture construction failure")

    engine = DspyAgentEngine(
        program_factory=broken, lm=ScriptedLM([]), cleanup=lambda: closed.append(True)
    )
    with pytest.raises(ValueError, match="fixture construction"):
        if streaming:
            _ = [
                update
                async for update in engine.stream(
                    user_request="fixture", history=None, context=CTX
                )
            ]
        else:
            await engine.run(user_request="fixture", history=None, context=CTX)
    assert closed == [True]


@pytest.mark.parametrize("error_type", [None, RuntimeError, ValueError])
async def test_stream_cleanup_waits_for_cancelled_worker(error_type):
    started = threading.Event()
    release = threading.Event()
    unwound = threading.Event()
    closed = []

    class Program(dspy.Module):
        synthesis_stream_fields = ("answer",)

        def __init__(self):
            super().__init__()
            self.synthesis = dspy.Predict("user_request -> answer")

        def forward(self, user_request, history):
            started.set()
            try:
                assert release.wait(5)
                if error_type is not None:
                    raise error_type("fixture worker failure")
                return self.synthesis(user_request=user_request)
            finally:
                unwound.set()

    def cleanup():
        assert unwound.is_set()
        closed.append(True)

    engine = DspyAgentEngine(
        program_factory=Program,
        lm=StreamingScriptedLM([synthesis_call(answer="fixture")]),
        cleanup=cleanup,
    )

    async def consume():
        return [
            update
            async for update in engine.stream(
                user_request="fixture", history=None, context=CTX
            )
        ]

    task = asyncio.create_task(consume())
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert closed == []
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 5)
        assert closed == [True]
    finally:
        release.set()


async def test_builder_failure_closes_lm_and_web_clients(monkeypatch, tmp_path):
    closed = []
    monkeypatch.setattr("app.agent.factory.close_lm", lambda lm: closed.append("lm"))

    class WebBundle:
        tools = []

        def close(self):
            closed.append("web")

    monkeypatch.setattr(
        "app.agent.factory._build_web_tools", lambda settings: WebBundle()
    )

    def broken(sources):
        raise RuntimeError("fixture registry failure")

    monkeypatch.setattr("app.agent.factory._build_tool_registry", broken)
    builder = make_engine_builder(Settings(), storage=LocalArtifactStorage(tmp_path))
    with pytest.raises(RuntimeError, match="fixture registry"):
        builder(RunEventBus(asyncio.get_running_loop()), thread_id="fixture")
    assert closed == ["web", "lm"]
