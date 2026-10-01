import asyncio

import pytest
from pydantic import SecretStr

from app.agent.engine import DspyAgentEngine
from app.agent.event_bus import RunEventBus
from app.agent.factory import build_dspy_engine, make_engine_builder
from app.agent.gateway import GatewayEngine, close_lm
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


def test_custom_base_url_uses_the_native_gateway():
    engine = build_dspy_engine(make_settings(llm_base_url="http://localhost:4000/v1"))  # type: ignore[arg-type]
    assert isinstance(engine._lm.engine, GatewayEngine)
    # Model ids reach custom gateways verbatim, with no LiteLLM prefixing.
    assert engine._lm.model == "fleet-gateway/openai/test-model"


def test_hosted_models_without_a_base_url_use_native_routing():
    import dspy

    engine = build_dspy_engine(make_settings())
    assert isinstance(engine._lm, dspy.LM)
    assert engine._lm.engine == "lm15"
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
    "configured_key", [None, "dtn_literal_key", "dapi_literal_key"]
)
def test_gateway_credentials_are_never_substituted(monkeypatch, configured_key):

    from app.agent.factory import _build_lm

    monkeypatch.setenv("DATABRICKS_TOKEN", "unrelated-token")
    lm = _build_lm(
        make_settings(
            llm_base_url="https://workspace.databricks.com/v1",
            llm_api_key=SecretStr(configured_key) if configured_key else None,
        )
    )
    try:
        assert lm.engine.config.api_keys == (
            {"fleet-gateway": configured_key} if configured_key else {}
        )
        assert lm.engine.config.env == {}
    finally:
        close_lm(lm)
