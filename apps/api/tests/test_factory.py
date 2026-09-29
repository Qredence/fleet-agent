import asyncio

import pytest
from pydantic import SecretStr

from app.agent.engine import DspyAgentEngine
from app.agent.event_bus import RunEventBus
from app.agent.factory import build_dspy_engine, make_engine_builder
from app.agent.openai_compatible import OpenAICompatibleLM
from app.services.artifact_storage import LocalArtifactStorage
from app.settings import Settings


def make_settings(**overrides) -> Settings:
    values = {
        "llm_model": "openai/test-model",
        "llm_api_key": SecretStr("sk-test-123"),
        "llm_max_iters": 6,
    }
    values.update(overrides)
    return Settings(**values)


def test_factory_builds_engine():
    engine = build_dspy_engine(make_settings())
    assert isinstance(engine, DspyAgentEngine)


def test_factory_omits_workspace_tools_without_production_root(tmp_path):
    settings = make_settings(environment="production", workspace_root=None)
    loop = asyncio.new_event_loop()
    bus = RunEventBus(loop)
    try:
        builder = make_engine_builder(
            settings,
            storage=LocalArtifactStorage(tmp_path),
        )
        engine = builder(bus, thread_id="thread-test")
        program = engine._program_factory()
    finally:
        loop.close()

    for route in ("workspace_read", "workspace_write", "workspace_shell"):
        assert not set(program.tool_names[route]) & {
            "ls",
            "find",
            "grep",
            "read",
            "write",
            "edit",
            "bash",
        }


def test_api_key_never_appears_in_reprs():
    settings = make_settings()
    engine = build_dspy_engine(make_settings())

    assert "sk-test-123" not in repr(settings)
    assert "sk-test-123" not in str(settings.llm_api_key)
    assert "sk-test-123" not in repr(engine)


def test_custom_base_url_uses_the_openai_compatible_client():
    engine = build_dspy_engine(make_settings(llm_base_url="http://localhost:4000/v1"))  # type: ignore[arg-type]
    assert isinstance(engine._lm, OpenAICompatibleLM)
    assert engine._lm.api_base == "http://localhost:4000/v1"
    # Model ids reach custom gateways verbatim, with no LiteLLM prefixing.
    assert engine._lm._gateway_model_id == "test-model"


def test_hosted_models_without_a_base_url_keep_litellm_routing():
    import dspy

    engine = build_dspy_engine(make_settings())
    assert isinstance(engine._lm, dspy.LM)
    assert not isinstance(engine._lm, OpenAICompatibleLM)
    assert engine._lm.kwargs.get("api_base") is None


def test_custom_gateway_advertises_function_calling():
    engine = build_dspy_engine(make_settings(llm_base_url="http://localhost:4000/v1"))
    assert engine._lm.supports_function_calling is True


def test_factory_can_use_json_tool_protocol_for_gateway():
    engine = build_dspy_engine(
        make_settings(
            llm_base_url="http://localhost:4000/v1",
            llm_native_function_calling=False,
        )
    )
    assert engine._adapter.use_native_function_calling is False


def test_web_tool_bundle_is_optional_and_owns_cleanup():
    from app.agent.factory import _build_web_tools

    assert _build_web_tools(Settings()) is None

    bundle = _build_web_tools(make_settings(tavily_api_key="tvly-test"))
    assert bundle is not None
    assert [tool.__name__ for tool in bundle.tools] == ["web_search", "fetch_page"]
    bundle.close()
    bundle.close()


def test_base_url_defaults_to_none():
    engine = build_dspy_engine(make_settings())
    assert engine._lm.kwargs.get("api_base") is None


@pytest.mark.parametrize(
    "api_base",
    [
        "https://example.gcp.databricks.com/ai-gateway/openai/v1",
        "https://DATABRICKS.COM./ai-gateway/openai/v1",
    ],
)
def test_databricks_gateway_replaces_daytona_key_with_workspace_token(
    monkeypatch, api_base
):
    from app.agent.factory import _build_lm

    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-workspace-token")
    settings = make_settings(
        llm_base_url=api_base,
        llm_api_key=SecretStr("dtn_not_a_workspace_token"),
        modal_model_id=None,
    )
    lm = _build_lm(settings, None)
    assert isinstance(lm, OpenAICompatibleLM)
    assert lm.api_key == "dapi-workspace-token"


@pytest.mark.parametrize("configured_key", [None, "dtn_unusable"])
@pytest.mark.parametrize("source", ["environment", "dotenv"])
@pytest.mark.parametrize("primary", [None, "", "dapi-primary"])
def test_databricks_token_uses_first_nonempty_alias(
    monkeypatch, tmp_path, configured_key, source, primary
):
    from app.agent.factory import _build_lm

    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    monkeypatch.delenv("DATABRICKS_API_TOKEN", raising=False)
    tokens = {"DATABRICKS_API_TOKEN": "dapi-secondary"}
    if primary is not None:
        tokens["DATABRICKS_TOKEN"] = primary
    env_file = tmp_path / "settings.env"
    if source == "environment":
        for key, value in tokens.items():
            monkeypatch.setenv(key, value)
    else:
        env_file.write_text(
            "\n".join(f"{key}={value}" for key, value in tokens.items())
        )

    settings = make_settings(
        _env_file=env_file if source == "dotenv" else None,
        llm_base_url="https://example.gcp.databricks.com/ai-gateway/openai/v1",
        llm_api_key=SecretStr(configured_key) if configured_key else None,
        modal_model_id=None,
    )
    lm = _build_lm(settings, None)
    assert isinstance(lm, OpenAICompatibleLM)
    assert lm.api_key == (primary or "dapi-secondary")


@pytest.mark.parametrize(
    "api_base",
    [
        "http://localhost:4000/v1",
        "https://example.com/databricks.com/ai-gateway/openai/v1",
        "https://databricks.com.evil.example/ai-gateway/openai/v1",
        "https://databricks.com@evil.example/ai-gateway/openai/v1",
    ],
)
def test_databricks_lookalikes_keep_configured_key(monkeypatch, api_base):
    from app.agent.factory import _build_lm

    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-workspace-token")
    settings = make_settings(
        llm_base_url=api_base,
        llm_api_key=SecretStr("dtn_keep_this_key"),
        modal_model_id=None,
    )
    lm = _build_lm(settings, None)
    assert isinstance(lm, OpenAICompatibleLM)
    assert lm.api_key == "dtn_keep_this_key"
