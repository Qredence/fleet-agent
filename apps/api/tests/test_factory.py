from pydantic import SecretStr

from app.agent.engine import DspyAgentEngine
from app.agent.factory import build_dspy_engine
from app.settings import Settings


def make_settings(**overrides) -> Settings:
    return Settings(
        llm_model="openai/test-model",
        llm_api_key=SecretStr("sk-test-123"),
        llm_max_iters=6,
        **overrides,
    )


def test_factory_builds_engine():
    engine = build_dspy_engine(make_settings())
    assert isinstance(engine, DspyAgentEngine)


def test_api_key_never_appears_in_reprs():
    settings = make_settings()
    engine = build_dspy_engine(make_settings())

    assert "sk-test-123" not in repr(settings)
    assert "sk-test-123" not in str(settings.llm_api_key)
    assert "sk-test-123" not in repr(engine)


def test_base_url_passes_through_to_litellm():
    engine = build_dspy_engine(make_settings(llm_base_url="http://localhost:4000/v1"))  # type: ignore[arg-type]
    assert engine._lm.kwargs["api_base"] == "http://localhost:4000/v1"


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
    make = make_settings()
    print("\nmake llm_base_url:", repr(make.llm_base_url))
    engine = build_dspy_engine(make)
    print("engine kwargs api_base:", engine._lm.kwargs.get("api_base"))
    assert engine._lm.kwargs.get("api_base") is None


def test_factory_selects_opt_in_staged_program(tmp_path):
    import asyncio

    from app.agent.factory import make_engine_builder
    from app.agent.staged import StagedDspyEngine
    from app.agui.event_bus import RunEventBus
    from app.services.artifact_storage import LocalArtifactStorage

    settings = make_settings(reasoning_program="staged")
    builder = make_engine_builder(
        settings, storage=LocalArtifactStorage(tmp_path / "artifacts")
    )
    loop = asyncio.new_event_loop()
    try:
        engine = builder(RunEventBus(loop), thread_id="thread-1")
    finally:
        loop.close()

    assert isinstance(engine, StagedDspyEngine)
    assert engine._registry.get("write_report").metadata.read_only is False
    assert engine._registry.get("write_report").metadata.parallelizable is False
