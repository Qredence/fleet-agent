"""Build run-scoped FleetAgent programs and their DSPy runtime boundary."""

from __future__ import annotations

import logging
import os
from urllib.parse import urlsplit

import dspy

from app.agent.approval import offered_tool_names
from app.agent.callbacks import AgUiRunCallback
from app.agent.engine import AgentEngine, DspyAgentEngine, EngineBuilder
from app.agent.event_bus import RunEventBus
from app.agent.openai_compatible import OpenAICompatibleLM
from app.agent.program import FleetAgent
from app.agent.provider import (
    OPENROUTER_API_BASE_URL,
    OPENROUTER_APP_TITLE,
    ProviderOverride,
)
from app.agent.routing import ToolRoute, read_router_state
from app.agent.tool_registry import (
    TOOL_SPECS,
    ToolCapability,
    ToolMetadata,
    ToolRegistry,
    workspace_root,
    workspace_root_available,
)
from app.agent.tooling import ToolSource
from app.agent.tools import get_current_time, search_docs
from app.agent.tools.docs import SearchDocsTool
from app.agent.tools.report import WriteReportTool
from app.agent.tools.web import WebToolBundle, build_web_tool_bundle
from app.agent.tools.workspace import WorkspacePolicy, WorkspaceTools
from app.services.artifact_storage import ArtifactStorage
from app.settings import Settings

logger = logging.getLogger(__name__)


def _resolve_gateway_api_key(api_key: str | None, api_base: str) -> str | None:
    """Pick a credential the gateway will actually accept.

    Databricks serving/AI Gateway rejects non-workspace tokens (Daytona
    ``dtn_…`` keys produce HTTP 401 "unsupported type"). When the configured
    key cannot work, prefer ``DATABRICKS_TOKEN`` from the environment.
    """
    try:
        hostname = urlsplit(api_base).hostname
    except ValueError:
        hostname = None
    if hostname is None:
        return api_key
    hostname = hostname.rstrip(".").lower()
    if hostname != "databricks.com" and not hostname.endswith(".databricks.com"):
        return api_key
    env_token = os.environ.get("DATABRICKS_TOKEN") or os.environ.get(
        "DATABRICKS_API_TOKEN"
    )
    if not env_token:
        return api_key
    if api_key is None or api_key.startswith("dtn_"):
        return env_token
    return api_key


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
        # operator's FLEET_AGENT_LLM_NATIVE_FUNCTION_CALLING selection.
        native_function_calling = _native_function_calling(settings, override)
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
            api_key=_resolve_gateway_api_key(api_key, api_base),
            api_base=api_base,
            temperature=settings.llm_temperature,
            cache=False,
            supports_native_function_calling=native_function_calling,
            use_developer_role=use_developer_role,
            extra_headers=extra_headers,
        )

    # Hosted providers keep LiteLLM routing, where the provider prefix in the
    # model id is meaningful and capability tables are known.
    return dspy.LM(
        model=model,
        api_key=api_key,
        api_base=None,
        temperature=settings.llm_temperature,
        cache=False,
        use_developer_role=use_developer_role,
    )


def _native_function_calling(
    settings: Settings, override: ProviderOverride | None
) -> bool:
    """Resolve native tool calls once, for both the LM and its adapter.

    An override that does not pin a response format inherits the operator's
    FLEET_AGENT_LLM_NATIVE_FUNCTION_CALLING selection, which exists precisely
    for gateways that reject native tool calls.
    """
    if override is None or override.response_format is None:
        return settings.llm_native_function_calling
    return override.response_format == "native_function_calling"


def _build_adapter(
    settings: Settings, override: ProviderOverride | None = None
) -> dspy.JSONAdapter:
    """Build the JSON adapter matching the active response format."""
    return dspy.JSONAdapter(
        use_native_function_calling=_native_function_calling(settings, override)
    )


def _source_name(source: ToolSource) -> str:
    if isinstance(source, dspy.Tool):
        return str(source.name or "")
    return str(getattr(source, "__name__", type(source).__name__))


def _build_tool_registry(sources: list[ToolSource]) -> ToolRegistry:
    """Create the single run-scoped source of truth for DSPy tools.

    Metadata comes from ``TOOL_SPECS``, the one table that also renders the
    public Tools page. A tool that is executable but undeclared fails here, at
    engine-build time, instead of reaching the model without policy.
    """
    registrations: list[tuple[ToolSource, ToolMetadata]] = []
    for source in sources:
        name = _source_name(source)
        try:
            metadata = TOOL_SPECS[name]
        except KeyError as exc:
            raise RuntimeError(
                f"tool {name!r} is executable but missing from TOOL_SPECS"
            ) from exc
        registrations.append((source, metadata))
    return ToolRegistry(registrations)


def build_tool_profiles(
    registry: ToolRegistry,
    approved: frozenset[str] | None = None,
) -> dict[ToolRoute, list[dspy.Tool]]:
    """Build the least-privileged capability lattice for routed ReActV2.

    Tools whose policy requires approval are dropped unless this run authorized
    them, so a gated tool is never merely declined - it is never offered, and the
    model cannot be talked into calling it.
    """
    offered = offered_tool_names(registry.approval_policy(), approved)
    research: set[ToolCapability] = {"retrieval", "utility"}
    workspace_read = set(research)
    workspace_read.add("workspace_read")
    workspace_write = set(workspace_read)
    workspace_write.add("workspace_write")
    workspace_shell = set(workspace_write)
    workspace_shell.add("shell")

    def for_capabilities(capabilities: set[ToolCapability]) -> list[dspy.Tool]:
        return [
            tool
            for tool in registry.dspy_tools_for_capabilities(capabilities)
            if tool.name in offered
        ]

    return {
        "direct": [],
        "research": for_capabilities(research),
        "artifact": for_capabilities(research | {"artifact"}),
        "workspace_read": for_capabilities(workspace_read),
        "workspace_write": for_capabilities(workspace_write),
        "workspace_shell": for_capabilities(workspace_shell),
    }


def build_dspy_engine(settings: Settings) -> AgentEngine:
    """Build the default engine used by focused backend tests."""
    lm = _build_lm(settings)
    adapter = _build_adapter(settings)
    registry = _build_tool_registry([search_docs, get_current_time])
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
) -> EngineBuilder:
    """Create run-scoped programs sharing immutable tool configuration.

    The LM and adapter are built per run inside ``build`` because a browser
    provider override (key, base URL, response format, messages format) can
    change them for a single request. ``approved`` carries the run's approval
    decision, which decides whether gated tools are offered to the model at all.

    Nothing here takes a database session: the agent layer has no storage
    dependency, so it can be built, tested, and optimized on its own.
    """

    # Read and validate a promoted router artifact once, here, rather than on
    # every request: the operator pinned a file, so a bad one fails at build time.
    router_instructions = (
        read_router_state(settings.router_state_path)
        if settings.router_state_path
        else None
    )
    if router_instructions is not None:
        # Operator-facing startup fact, not per-run chatter: warn so it survives
        # a default logging setup. The app's own INFO records are dropped unless
        # the operator configures a root handler, and a pinned artifact that
        # cannot be confirmed is indistinguishable from one that was ignored.
        logger.warning(
            "using promoted router instructions from %s", settings.router_state_path
        )

    def build(
        bus: RunEventBus,
        *,
        thread_id: str,
        provider_override: ProviderOverride | None = None,
        approved: frozenset[str] | None = None,
    ) -> AgentEngine:
        lm = _build_lm(settings, provider_override)
        adapter = _build_adapter(settings, provider_override)
        report_tool = WriteReportTool(
            storage=storage,
            bus=bus,
            thread_id=thread_id,
            max_bytes=settings.artifact_max_bytes,
        )
        web_bundle = _build_web_tools(settings)
        sources: list[ToolSource] = [
            *(web_bundle.tools if web_bundle else []),
            SearchDocsTool(),
            report_tool,
            get_current_time,
        ]
        if workspace_root_available(settings):
            workspace_tools = WorkspaceTools(
                WorkspacePolicy(
                    root=workspace_root(settings),
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

        registry = _build_tool_registry(sources)
        profiles = build_tool_profiles(registry, approved)
        callback = AgUiRunCallback(bus=bus, cancel_token=bus.cancel_token)

        def program_factory() -> FleetAgent:
            """The routed ReActV2 program over the least-privileged profiles."""
            return FleetAgent(
                tool_profiles=profiles,
                max_iters=settings.llm_max_iters,
                router_instructions=router_instructions,
            )

        return DspyAgentEngine(
            program_factory=program_factory,
            lm=lm,
            adapter=adapter,
            callbacks=[callback],
            cleanup=web_bundle.close if web_bundle else None,
        )

    return build
