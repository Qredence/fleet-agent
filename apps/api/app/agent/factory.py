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
from app.agent.staged import StagedDspyEngine
from app.agent.tool_registry import ToolMetadata, ToolRegistry
from app.agent.tools import get_current_time, search_docs
from app.agent.tools.docs import SearchDocsTool
from app.agent.tools.report import WriteReportTool
from app.agent.tools.web import WebToolBundle, build_web_tool_bundle
from app.agui.event_bus import RunEventBus
from app.agui.live_coordinator import EngineBuilder
from app.services.artifact_storage import ArtifactStorage
from app.settings import Settings


class _FleetLM(dspy.LM):  # type: ignore[misc]
    """LM with an explicit capability override for OpenAI-compatible gateways.

    LiteLLM cannot infer function-calling support for many gateway-specific
    model names. When native mode is explicitly enabled, DSPy would otherwise
    omit the tools while ReActV2 still requests a forced tool choice during
    final submission. Custom OpenAI-compatible endpoints can advertise that
    capability through this adapter.
    """

    def __init__(self, *, force_function_calling: bool, **kwargs: Any) -> None:
        self._force_function_calling = force_function_calling
        super().__init__(**kwargs)

    @property
    def supports_function_calling(self) -> bool:
        return self._force_function_calling or super().supports_function_calling


def _build_lm(settings: Settings) -> dspy.LM:
    return _FleetLM(
        model=settings.llm_model,
        api_key=(
            settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
        ),
        api_base=settings.llm_base_url,
        temperature=settings.llm_temperature,
        cache=False,
        force_function_calling=(
            settings.llm_base_url is not None and settings.llm_native_function_calling
        ),
    )


def _build_adapter(settings: Settings) -> dspy.JSONAdapter:
    return dspy.JSONAdapter(
        use_native_function_calling=settings.llm_native_function_calling
    )


def build_dspy_engine(settings: Settings) -> AgentEngine:
    lm = _build_lm(settings)
    adapter = _build_adapter(settings)

    def agent_factory() -> dspy.ReActV2:
        return dspy.ReActV2(
            AgentSignature,
            tools=[search_docs, get_current_time],
            max_iters=settings.llm_max_iters,
        )

    return DspyReActV2Engine(agent_factory=agent_factory, lm=lm, adapter=adapter)


def _build_web_tools(settings: Settings) -> WebToolBundle | None:
    """Tavily-backed web tools; empty when no API key is configured."""
    if not settings.tavily_api_key:
        return None
    return build_web_tool_bundle(
        api_key=settings.tavily_api_key.get_secret_value(),
        dns_fallback=settings.tavily_dns_fallback,
    )


def make_engine_builder(
    settings: Settings, *, storage: ArtifactStorage
) -> EngineBuilder:
    """Per-run engines over shared LM/adapter, using native DSPy callbacks.

    The LM and adapter are stateless config objects safe to share across runs
    and threads; every run gets its own ReActV2 instance, tool objects, and
    native callbacks so domain events land in that run's event bus only.
    Web search/fetch are per-run too; their result-id registry never crosses
    runs.
    """
    lm = _build_lm(settings)
    adapter = _build_adapter(settings)

    def build(bus: RunEventBus, *, thread_id: str) -> AgentEngine:
        docs_tool = SearchDocsTool()
        report_tool = WriteReportTool(
            storage=storage,
            bus=bus,
            thread_id=thread_id,
            max_bytes=settings.artifact_max_bytes,
            step_id="step-synthesis"
            if settings.reasoning_program == "staged"
            else None,
        )
        web_bundle = _build_web_tools(settings)
        tools: list[Callable[..., Any]] = [
            *(web_bundle.tools if web_bundle else []),
            docs_tool,
            report_tool,
            get_current_time,
        ]
        callback = AgUiRunCallback(bus=bus, cancel_token=bus.cancel_token)

        registry = ToolRegistry(
            [
                (
                    tool,
                    ToolMetadata(
                        name=tool.__name__,
                        read_only=tool is not report_tool,
                        idempotent=tool is not get_current_time,
                        parallelizable=(
                            tool is not report_tool and tool is not get_current_time
                        ),
                        timeout_seconds=settings.reasoning_task_timeout_seconds,
                    ),
                )
                for tool in tools
            ]
        )

        if settings.reasoning_program == "staged":
            return StagedDspyEngine(
                lm=lm,
                adapter=adapter,
                registry=registry,
                bus=bus,
                max_parallel_tasks=settings.reasoning_max_parallel_tasks,
                max_model_calls=settings.reasoning_max_model_calls,
                max_tool_calls=settings.reasoning_max_tool_calls,
                task_timeout_seconds=settings.reasoning_task_timeout_seconds,
                researcher_max_iters=settings.llm_max_iters,
                cleanup=web_bundle.close if web_bundle else None,
            )

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
            cleanup=web_bundle.close if web_bundle else None,
        )

    return build
