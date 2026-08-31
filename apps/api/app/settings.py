import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

_APP_DIR = Path(__file__).resolve().parent
_ENV_FILE = os.environ.get("FLEET_AGENT_ENV_FILE", str(_APP_DIR.parent / ".env"))


class Settings(BaseSettings):
    """Application configuration, validated at startup."""

    model_config = SettingsConfigDict(
        env_prefix="FLEET_AGENT_",
        # apps/api/.env — resolved absolutely, independent of process CWD;
        # tests redirect to /dev/null via FLEET_AGENT_ENV_FILE (never inherit .env).
        env_file=_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
        # Provider default fields use validation_alias (MODAL_*), so allow
        # constructing Settings(modal_model_id=...) by field name in tests.
        populate_by_name=True,
    )

    environment: str = Field(default="development")
    cors_origins: list[str] = Field(
        default=["http://localhost:5173"],
        description="Exact origins allowed to call the API. No wildcards.",
    )
    cors_allow_credentials: bool = Field(default=True)

    llm_model: str = Field(
        default="openai/gpt-4o-mini",
        description="LiteLLM model identifier for the DSPy engine.",
    )
    llm_base_url: str | None = Field(
        default=None,
        description=(
            "Optional OpenAI-compatible endpoint base URL for proxies, Azure "
            "OpenAI, or local inference servers. With a base URL set, the "
            "model identifier is sent to the gateway verbatim."
        ),
    )
    llm_api_key: SecretStr | None = Field(
        default=None,
        description="Provider API key. Never logged or returned by the API.",
    )
    llm_max_iters: int = Field(
        default=6,
        ge=1,
        le=25,
        description="Hard bound on ReActV2 loop iterations per run.",
    )
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    llm_native_function_calling: bool = Field(
        default=True,
        description=(
            "Use provider-native function calling. Disable for gateways that "
            "support DSPy JSON tool calls but not native tool calls."
        ),
    )
    llm_allow_private_base_urls: bool = Field(
        default=False,
        description=(
            "Allow browser provider overrides to target loopback/private base "
            "URLs, e.g. a local LLM server. Off by default: the browser must "
            "not be able to direct the server at internal addresses."
        ),
    )
    modal_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Default provider API key for local runs (reads MODAL_API_KEY). "
            "Server-side default when the browser sends no provider override; "
            "never logged or returned by the API."
        ),
        validation_alias="MODAL_API_KEY",
    )
    modal_base_url: str | None = Field(
        default=None,
        description=(
            "Default OpenAI-compatible endpoint base URL (reads MODAL_BASE_URL), "
            "e.g. a Modal proxy gateway."
        ),
        validation_alias="MODAL_BASE_URL",
    )
    modal_model_id: str | None = Field(
        default=None,
        description=(
            "Default model identifier (reads MODAL_MODEL_ID), sent to the "
            "gateway verbatim. When set, the MODAL_* trio takes precedence "
            "over FLEET_AGENT_LLM_* as the server-side default provider."
        ),
        validation_alias="MODAL_MODEL_ID",
    )
    openrouter_http_referer: str | None = Field(
        default=None,
        description=(
            "Trusted server-side HTTP referer sent to OpenRouter for BYOK runs. "
            "Never accept this value from browser request headers."
        ),
    )

    agent_mode: Literal["fixtures", "engine"] = Field(
        default="fixtures",
        description=(
            "'fixtures' replays the canonical NDJSON mock streams (dev/CI "
            "default); 'engine' runs the live DSPy ReActV2 bridge (production)."
        ),
    )
    reasoning_program: Literal["react", "staged", "flex"] = Field(
        default="react",
        description="Reasoning strategy. Staged is opt-in while it is validated.",
    )
    reasoning_max_parallel_tasks: int = Field(
        default=4,
        ge=1,
        le=4,
        description="Maximum concurrent read-only staged research tasks.",
    )
    reasoning_max_model_calls: int = Field(
        default=8,
        ge=1,
        le=32,
        description="Server-capped staged DSPy model-call budget.",
    )
    reasoning_max_tool_calls: int = Field(
        default=12,
        ge=1,
        le=64,
        description="Server-capped staged tool-call budget.",
    )
    reasoning_task_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=120.0,
        description="Server-capped timeout for one staged research task.",
    )

    workspace_root: str | None = Field(
        default=None,
        description=(
            "Workspace root available to filesystem tools. Development defaults "
            "to the repository root; other environments must configure it."
        ),
    )
    workspace_read_tools_enabled: bool = Field(default=True)
    workspace_write_tools_enabled: bool = Field(default=False)
    workspace_bash_tool_enabled: bool = Field(default=False)
    workspace_max_read_bytes: int = Field(default=256 * 1024, gt=0)
    workspace_max_write_bytes: int = Field(default=1024 * 1024, gt=0)
    workspace_max_output_chars: int = Field(default=12_000, gt=0)
    workspace_bash_default_timeout_seconds: int = Field(default=30, ge=1, le=120)
    workspace_bash_max_timeout_seconds: int = Field(default=120, ge=1, le=300)

    flex_enabled: bool = Field(
        default=False,
        description=(
            "Enable the experimental Flex runtime path explicitly. The "
            "read-only Flex track requires a local Deno runtime "
            "(>= 2.0.0, < 3.0.0) on PATH for the sandboxed interpreter."
        ),
    )
    flex_allow_mutating_tools: bool = Field(default=False)
    flex_max_predictor_calls: int = Field(default=12, ge=1, le=100)

    router_state_path: str | None = Field(
        default=None,
        description=(
            "Path to a promoted Flex router state JSON produced by "
            "`python -m evals.optimize`. When set, the routed program loads "
            "the GEPA-evolved router (Deno-sandboxed, fail-fast) instead of "
            "the baseline Predict. Unset keeps the baseline router."
        ),
    )

    mlflow_tracing_enabled: bool = Field(
        default=False,
        description=(
            "Opt-in MLflow tracing of live dspy runs (predictor, ReAct, tool "
            "spans) via mlflow.dspy.autolog. Off by default: traces capture "
            "LLM prompts/completions by design, so enabling is an explicit "
            "operator decision for their own observability store."
        ),
    )
    mlflow_tracking_uri: str | None = Field(
        default=None,
        description=(
            "MLflow tracking URI (defaults to the local gitignored file "
            "store under .artifacts/mlflow). FLEET_AGENT_MLFLOW_TRACKING_URI "
            "and MLFLOW_TRACKING_URI env vars take precedence."
        ),
    )

    database_url: SecretStr = Field(
        default=SecretStr(
            "postgresql+asyncpg://fleet:fleet@localhost:5432/fleet_agent"
        ),
        description="SQLAlchemy async URL. Never logged.",
    )

    artifacts_dir: str = Field(
        default=".artifacts",
        description=(
            "Local artifact storage root (dev). Controlled download URLs are "
            "endpoint-served; production swaps in object storage behind the "
            "same ArtifactStorage protocol."
        ),
    )
    artifact_max_bytes: int = Field(default=64 * 1024, gt=0)

    # PR 9 — hardening
    run_timeout_seconds: float = Field(
        default=300.0, gt=0, description="Hard bound on one agent run."
    )
    max_concurrent_runs: int = Field(
        default=4, ge=1, description="Engine-mode global run concurrency cap."
    )
    max_body_bytes: int = Field(
        default=1024 * 1024,
        gt=0,
        description="Reject larger request bodies with 413.",
    )
    api_key: SecretStr | None = Field(
        default=None,
        description=(
            "When set, /api/* requires the X-API-Key header to match. "
            "Unset = open local/dev mode (log an advisory at startup)."
        ),
    )

    tavily_api_key: SecretStr | None = Field(
        default=None,
        description=(
            "Tavily API key. When set, the engine gains web_search and "
            "fetch_page tools (Tavily REST). Never logged or returned."
        ),
    )
    tavily_dns_fallback: bool = Field(
        default=False,
        description=(
            "Use UDP public DNS only when the system resolver cannot resolve "
            "api.tavily.com. Useful in restricted local runtimes."
        ),
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
