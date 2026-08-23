"""Builds the production DspyReActV2Engine from Settings.

Native function calling is configured explicitly (JSONAdapter enables it by
default; being explicit keeps behavior stable across DSPy patch releases).
"""

from collections.abc import Callable
from typing import Any

import dspy

from app.agent.callbacks import AgUiRunCallback
from app.agent.engine import AgentEngine, DspyReActV2Engine
from app.agent.signature import AgentSignature
from app.agent.tools import get_current_time, search_docs
from app.agent.tools.docs import SearchDocsTool
from app.agent.tools.report import WriteReportTool
from app.agui.event_bus import RunEventBus
from app.agui.live_coordinator import EngineBuilder
from app.services.artifact_storage import ArtifactStorage
from app.settings import Settings


def _build_lm(settings: Settings) -> dspy.LM:
    return dspy.LM(
        settings.llm_model,
        api_key=(
            settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
        ),
        api_base=settings.llm_base_url,
        temperature=settings.llm_temperature,
        cache=False,
    )


def _build_adapter() -> dspy.JSONAdapter:
    return dspy.JSONAdapter(use_native_function_calling=True)


def build_dspy_engine(settings: Settings) -> AgentEngine:
    lm = _build_lm(settings)
    adapter = _build_adapter()

    def agent_factory() -> dspy.ReActV2:
        return dspy.ReActV2(
            AgentSignature,
            tools=[search_docs, get_current_time],
            max_iters=settings.llm_max_iters,
        )

    return DspyReActV2Engine(agent_factory=agent_factory, lm=lm, adapter=adapter)


def make_engine_builder(
    settings: Settings, *, storage: ArtifactStorage
) -> EngineBuilder:
    """Per-run engines over shared LM/adapter, using native DSPy callbacks.

    The LM and adapter are stateless config objects safe to share across runs
    and threads; every run gets its own ReActV2 instance, tool objects, and
    native callbacks so domain events land in that run's event bus only.
    """
    lm = _build_lm(settings)
    adapter = _build_adapter()

    def build(bus: RunEventBus, *, thread_id: str) -> AgentEngine:
        docs_tool = SearchDocsTool()
        report_tool = WriteReportTool(
            storage=storage,
            bus=bus,
            thread_id=thread_id,
            max_bytes=settings.artifact_max_bytes,
        )
        tools: list[Callable[..., Any]] = [
            docs_tool,
            report_tool,
            get_current_time,
        ]
        callback = AgUiRunCallback(bus=bus, cancel_token=bus.cancel_token)

        def agent_factory() -> dspy.ReActV2:
            return dspy.ReActV2(
                AgentSignature,
                tools=tools,
                max_iters=settings.llm_max_iters,
            )

        return DspyReActV2Engine(
            agent_factory=agent_factory,
            lm=lm,
            adapter=adapter,
            callbacks=[callback],
        )

    return build
