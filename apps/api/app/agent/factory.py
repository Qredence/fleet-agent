"""Build run-scoped FleetAgent programs and their DSPy runtime boundary."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import dspy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agent.callbacks import AgUiRunCallback
from app.agent.engine import AgentEngine, DspyAgentEngine
from app.agent.flex_program import FlexFleetAgent, ensure_deno_runtime
from app.agent.flex_router import load_flex_router
from app.agent.openai_compatible import OpenAICompatibleLM
from app.agent.program import FleetAgent
from app.agent.provider import (
    OPENROUTER_API_BASE_URL,
    OPENROUTER_APP_TITLE,
    ProviderOverride,
)
from app.agent.routing import ToolRoute
from app.agent.staged import StagedDspyEngine
from app.agent.tool_registry import (
    ToolCapability,
    ToolMetadata,
    ToolRegistry,
    wrap_tool_with_guard,
)
from app.agent.tooling import ToolSource
from app.agent.tools import get_current_time, search_docs
from app.agent.tools.docs import SearchDocsTool
from app.agent.tools.report import WriteReportTool
from app.agent.tools.web import WebToolBundle, build_web_tool_bundle
from app.agent.tools.workspace import WorkspacePolicy, WorkspaceTools
from app.agent.tools_catalog import tool_catalog_by_name
from app.agui.event_bus import RunEventBus
from app.agui.live_coordinator import EngineBuilder
from app.services.artifact_storage import ArtifactStorage
from app.services.durable_approvals import DurableApprovalRegistry
from app.settings import Settings

logger = logging.getLogger(__name__)


def _promoted_router_src(settings: Settings) -> str | None:
    """Validate the operator-pinned router state once, at startup.

    Returns the promoted ``module_src`` (the only state a Flex router
    carries), or ``None`` when no artifact is pinned. A malformed artifact or
    a missing Deno runtime fails here, at engine-builder construction, rather
    than on the first routed request.
    """
    if not settings.router_state_path:
        return None
    from app.agent.flex_router import load_flex_router_from_file

    router = load_flex_router_from_file(settings.router_state_path)
    logger.info("loaded promoted Flex router state from %s", settings.router_state_path)
    return router.module_src()


class _FleetLM(dspy.LM):  # type: ignore[misc]
    """LM with an explicit capability override for compatible gateways."""

    def __init__(self, *, force_function_calling: bool, **kwargs: Any) -> None:
        self._force_function_calling = force_function_calling
        super().__init__(**kwargs)

    @property
    def supports_function_calling(self) -> bool:
        return self._force_function_calling or super().supports_function_calling


def _build_lm(
    settings: Settings, override: ProviderOverride | None = None
) -> dspy.BaseLM:
    """Build the run LM: browser override, then MODAL_*, then LLM settings.

    Precedence for the server-side default: the MODAL_API_KEY / MODAL_BASE_URL
    / MODAL_MODEL_ID trio (when MODAL_MODEL_ID is set), falling back to the
    FLEET_AGENT_LLM_* settings. A browser provider override always wins.

    Any provider configured with a base URL is by definition an
    OpenAI-compatible gateway, so it is served by ``OpenAICompatibleLM``
    (the OpenAI SDK, no LiteLLM routing) and its model id is sent verbatim.
    Hosted providers without a base URL keep ``dspy.LM`` and LiteLLM routing.
    """
    api_key: str | None
    if override is not None:
        model = override.model or settings.llm_model
        api_key = override.api_key
        api_base = override.api_base
        # An override that does not pin a response format inherits the
        # operator's FLEET_AGENT_LLM_NATIVE_FUNCTION_CALLING selection, which
        # exists precisely for gateways that reject native tool calls.
        native_function_calling = (
            settings.llm_native_function_calling
            if override.response_format is None
            else override.response_format == "native_function_calling"
        )
        use_developer_role = override.messages_format == "developer_role"
    elif settings.modal_model_id:
        model = settings.modal_model_id or settings.llm_model
        api_key = (
            settings.modal_api_key.get_secret_value()
            if settings.modal_api_key
            else None
        )
        api_base = settings.modal_base_url
        native_function_calling = settings.llm_native_function_calling
        use_developer_role = False
    else:
        model = settings.llm_model
        api_key = (
            settings.llm_api_key.get_secret_value() if settings.llm_api_key else None
        )
        api_base = settings.llm_base_url
        native_function_calling = settings.llm_native_function_calling
        use_developer_role = False

    extra_headers: dict[str, str] | None = None
    if (
        api_base is not None
        and api_base.rstrip("/") == OPENROUTER_API_BASE_URL
        and settings.openrouter_http_referer
    ):
        extra_headers = {
            "HTTP-Referer": settings.openrouter_http_referer,
            "X-Title": OPENROUTER_APP_TITLE,
        }

    if api_base is not None:
        return OpenAICompatibleLM(
            model=model,
            api_key=api_key,
            api_base=api_base,
            temperature=settings.llm_temperature,
            cache=False,
            supports_native_function_calling=native_function_calling,
            use_developer_role=use_developer_role,
            extra_headers=extra_headers,
        )

    # Hosted providers keep LiteLLM routing, where the provider prefix in the
    # model id is meaningful and capability tables are known.
    return _FleetLM(
        model=model,
        api_key=api_key,
        api_base=None,
        temperature=settings.llm_temperature,
        cache=False,
        force_function_calling=False,
        use_developer_role=use_developer_role,
    )


def _build_adapter(
    settings: Settings, override: ProviderOverride | None = None
) -> dspy.JSONAdapter:
    """Build the JSON adapter matching the active response format."""
    use_native_function_calling = (
        (
            settings.llm_native_function_calling
            if override.response_format is None
            else override.response_format == "native_function_calling"
        )
        if override is not None
        else settings.llm_native_function_calling
    )
    return dspy.JSONAdapter(use_native_function_calling=use_native_function_calling)


def _source_name(source: ToolSource) -> str:
    if isinstance(source, dspy.Tool):
        return str(source.name or "")
    return str(getattr(source, "__name__", type(source).__name__))


def _workspace_root(settings: Settings) -> Path:
    """Resolve the one server-configured workspace root, fail-closed in prod."""
    if settings.workspace_root:
        return Path(settings.workspace_root)
    if settings.environment == "development":
        # factory.py -> agent -> app -> api -> apps -> repository root
        return Path(__file__).resolve().parents[4]
    raise RuntimeError(
        "workspace_root must be explicitly configured outside development"
    )


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
                    capability=item.capability,
                    read_only=item.read_only,
                    idempotent=item.idempotent,
                    parallelizable=item.parallelizable,
                    timeout_seconds=item.timeout_seconds,
                    requires_approval=item.requires_approval,
                ),
            )
        )

    return ToolRegistry(registrations)


def build_tool_profiles(
    registry: ToolRegistry,
) -> dict[ToolRoute, list[dspy.Tool]]:
    """Build the least-privileged capability lattice for routed ReActV2."""
    research: set[ToolCapability] = {"retrieval", "utility"}
    workspace_read = set(research)
    workspace_read.add("workspace_read")
    workspace_write = set(workspace_read)
    workspace_write.add("workspace_write")
    workspace_shell = set(workspace_write)
    workspace_shell.add("shell")
    return {
        "direct": [],
        "research": registry.dspy_tools_for_capabilities(research),
        "artifact": registry.dspy_tools_for_capabilities(research | {"artifact"}),
        "workspace_read": registry.dspy_tools_for_capabilities(workspace_read),
        "workspace_write": registry.dspy_tools_for_capabilities(workspace_write),
        "workspace_shell": registry.dspy_tools_for_capabilities(workspace_shell),
    }


def build_dspy_engine(settings: Settings) -> AgentEngine:
    """Build the default engine used by focused backend tests."""
    lm = _build_lm(settings)
    adapter = _build_adapter(settings)
    registry = _build_tool_registry(settings, [search_docs, get_current_time])
    profiles = build_tool_profiles(registry)

    def program_factory() -> FleetAgent:
        return FleetAgent(
            tool_profiles=profiles,
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
    settings: Settings,
    *,
    storage: ArtifactStorage,
    sessions: async_sessionmaker[AsyncSession] | None = None,
) -> EngineBuilder:
    """Create run-scoped programs sharing immutable tool configuration.

    The LM and adapter are built per run inside ``build`` because a browser
    provider override (key, base URL, response format, messages format) can
    change them for a single request.  When ``sessions`` is provided, engine
    runs persist approval checkpoints durably so a paused run survives a
    server restart.
    """
    sessions_final = sessions
    router_src = _promoted_router_src(settings)

    def _build_router() -> dspy.Module | None:
        """Fresh Flex router per run-scoped program, or None for baseline.

        The promoted source is validated once above; rebuilding the module
        per program keeps run-scoped programs from sharing bridge state.
        """
        if router_src is None:
            return None
        return load_flex_router({"module_src": router_src})

    def build(
        bus: RunEventBus,
        *,
        thread_id: str,
        provider_override: ProviderOverride | None = None,
    ) -> AgentEngine:
        lm = _build_lm(settings, provider_override)
        adapter = _build_adapter(settings, provider_override)
        approval_registry = (
            DurableApprovalRegistry(
                sessions=sessions_final, loop=asyncio.get_running_loop()
            )
            if sessions_final is not None
            else None
        )
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
        if settings.workspace_read_tools_enabled:
            workspace_tools = WorkspaceTools(
                WorkspacePolicy(
                    root=_workspace_root(settings),
                    max_read_bytes=settings.workspace_max_read_bytes,
                    max_write_bytes=settings.workspace_max_write_bytes,
                    max_output_chars=settings.workspace_max_output_chars,
                    bash_default_timeout_seconds=(
                        settings.workspace_bash_default_timeout_seconds
                    ),
                    bash_max_timeout_seconds=settings.workspace_bash_max_timeout_seconds,
                    allow_write=settings.workspace_write_tools_enabled,
                    allow_bash=settings.workspace_bash_tool_enabled,
                )
            )
            sources.extend(workspace_tools.dspy_tools())
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

        profiles = build_tool_profiles(registry)
        approval_policy = registry.approval_policy()

        if settings.reasoning_program == "flex":
            if not settings.flex_enabled:
                raise RuntimeError("reasoning_program=flex requires flex_enabled=true")
            flex_capabilities: set[ToolCapability] = {
                "retrieval",
                "utility",
                "workspace_read",
            }
            if settings.flex_allow_mutating_tools:
                flex_capabilities.update({"artifact", "workspace_write", "shell"})
            # DSPy 3.3.1 swallows exceptions raised inside start callbacks,
            # so the read-only Flex path enforces cancellation on the tool
            # callable itself rather than through AgUiRunCallback hooks.
            flex_tools = [
                wrap_tool_with_guard(tool, bus.cancel_token.check)
                for tool in registry.dspy_tools_for_capabilities(flex_capabilities)
            ]

            # Flex executes tool calls inside its RLM interpreter, which catches
            # host-tool exceptions before the application can turn them into an
            # AG-UI interrupt.  Mutating Flex is therefore routed through the
            # same application-owned approval loop as the default program; the
            # read-only experimental path retains native Flex semantics.
            if settings.flex_allow_mutating_tools:

                def flex_safe_program_factory() -> FleetAgent:
                    return FleetAgent(
                        tool_profiles=profiles,
                        max_iters=settings.llm_max_iters,
                        approval_policy=approval_policy,
                        lifecycle=callback,
                    )

                return DspyAgentEngine(
                    program_factory=flex_safe_program_factory,
                    lm=lm,
                    adapter=adapter,
                    callbacks=[callback],
                    provider_override=provider_override,
                    lifecycle=callback,
                    cancel_token=bus.cancel_token,
                    approval_registry=approval_registry,
                    cleanup=web_bundle.close if web_bundle else None,
                )

            # The read-only Flex track runs dspy.Flex's Deno/Pyodide sandbox;
            # fail fast at engine-build time instead of on every request.
            ensure_deno_runtime()

            def flex_program_factory() -> FlexFleetAgent:
                return FlexFleetAgent(
                    tools=flex_tools,
                    max_predictor_calls=settings.flex_max_predictor_calls,
                )

            return DspyAgentEngine(
                program_factory=flex_program_factory,
                lm=lm,
                adapter=adapter,
                callbacks=[callback],
                provider_override=provider_override,
                cancel_token=bus.cancel_token,
                cleanup=web_bundle.close if web_bundle else None,
            )

        def program_factory() -> FleetAgent:
            return FleetAgent(
                tool_profiles=profiles,
                max_iters=settings.llm_max_iters,
                approval_policy=approval_policy,
                lifecycle=callback,
                router=_build_router(),
            )

        return DspyAgentEngine(
            program_factory=program_factory,
            lm=lm,
            adapter=adapter,
            callbacks=[callback],
            provider_override=provider_override,
            lifecycle=callback,
            cancel_token=bus.cancel_token,
            approval_registry=approval_registry,
            cleanup=web_bundle.close if web_bundle else None,
        )

    return build
