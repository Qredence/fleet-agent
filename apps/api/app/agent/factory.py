"""Build run-scoped FleetAgent programs and their DSPy runtime boundary."""

from __future__ import annotations

from typing import Any

import dspy

from app.agent.callbacks import AgUiRunCallback
from app.agent.engine import AgentEngine, DspyAgentEngine
from app.agent.program import FleetAgent
from app.agent.staged import StagedDspyEngine
from app.agent.tool_registry import ToolMetadata, ToolRegistry
from app.agent.tooling import ToolSource
from app.agent.tools import get_current_time, search_docs
from app.agent.tools.docs import SearchDocsTool
from app.agent.tools.report import WriteReportTool
from app.agent.tools.web import WebToolBundle, build_web_tool_bundle
from app.agent.tools_catalog import tool_catalog_by_name
from app.agui.event_bus import RunEventBus
from app.agui.live_coordinator import EngineBuilder
from app.services.artifact_storage import ArtifactStorage
from app.settings import Settings


class _FleetLM(dspy.LM):  # type: ignore[misc]
    """LM with an explicit capability override for compatible gateways."""

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


def _source_name(source: ToolSource) -> str:
    if isinstance(source, dspy.Tool):
        return str(source.name or "")
    return str(getattr(source, "__name__", type(source).__name__))


def _build_tool_registry(
    settings: Settings,
    sources: list[ToolSource],
) -> ToolRegistry:
    """Create the single run-scoped source of truth for DSPy tools."""
    catalog = tool_catalog_by_name(settings)
    registrations: list[tuple[ToolSource, ToolMetadata]] = []

    for source in sources:
        name = _source_name(source)
        try:
            item = catalog[name]
        except KeyError as exc:
            raise RuntimeError(
                f"tool {name!r} is executable but missing from tools_catalog.py"
            ) from exc
        registrations.append(
            (
                source,
                ToolMetadata(
                    name=item.name,
                    read_only=item.read_only,
                    idempotent=item.idempotent,
                    parallelizable=item.parallelizable,
                    timeout_seconds=item.timeout_seconds,
                ),
            )
        )

    return ToolRegistry(registrations)


def build_dspy_engine(settings: Settings) -> AgentEngine:
    """Build the default engine used by focused backend tests."""
    lm = _build_lm(settings)
    adapter = _build_adapter(settings)
    registry = _build_tool_registry(settings, [search_docs, get_current_time])

    def program_factory() -> FleetAgent:
        return FleetAgent(
            tools=registry.dspy_tools(),
            max_iters=settings.llm_max_iters,
        )

    return DspyAgentEngine(
        program_factory=program_factory,
        lm=lm,
        adapter=adapter,
    )


def _build_web_tools(settings: Settings) -> WebToolBundle | None:
    """Build Tavily-backed web tools when an API key is configured."""
    if not settings.tavily_api_key:
        return None
    return build_web_tool_bundle(
        api_key=settings.tavily_api_key.get_secret_value(),
        dns_fallback=settings.tavily_dns_fallback,
    )


def make_engine_builder(
    settings: Settings, *, storage: ArtifactStorage
) -> EngineBuilder:
    """Create run-scoped programs while sharing immutable LM configuration."""
    lm = _build_lm(settings)
    adapter = _build_adapter(settings)

    def build(bus: RunEventBus, *, thread_id: str) -> AgentEngine:
        docs_tool = SearchDocsTool()
        report_tool = WriteReportTool(
            storage=storage,
            bus=bus,
            thread_id=thread_id,
            max_bytes=settings.artifact_max_bytes,
            step_id=(
                "step-synthesis" if settings.reasoning_program == "staged" else None
            ),
        )
        web_bundle = _build_web_tools(settings)
        sources: list[ToolSource] = [
            *(web_bundle.tools if web_bundle else []),
            docs_tool,
            report_tool,
            get_current_time,
        ]
        registry = _build_tool_registry(settings, sources)
        callback = AgUiRunCallback(bus=bus, cancel_token=bus.cancel_token)

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

        def program_factory() -> FleetAgent:
            return FleetAgent(
                tools=registry.dspy_tools(),
                max_iters=settings.llm_max_iters,
            )

        return DspyAgentEngine(
            program_factory=program_factory,
            lm=lm,
            adapter=adapter,
            callbacks=[callback],
            cleanup=web_bundle.close if web_bundle else None,
        )

    return build
