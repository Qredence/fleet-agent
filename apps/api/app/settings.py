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
            "Optional OpenAI-compatible endpoint base URL (litellm api_base) "
            "for proxies, Azure OpenAI, or local inference servers."
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

    agent_mode: Literal["fixtures", "engine"] = Field(
        default="fixtures",
        description=(
            "'fixtures' replays the canonical NDJSON mock streams (dev/CI "
            "default); 'engine' runs the live DSPy ReActV2 bridge (production)."
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
