from pydantic import SecretStr

from app.agent.engine import DspyReActV2Engine
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
    assert isinstance(engine, DspyReActV2Engine)


def test_api_key_never_appears_in_reprs():
    settings = make_settings()
    engine = build_dspy_engine(make_settings())

    assert "sk-test-123" not in repr(settings)
    assert "sk-test-123" not in str(settings.llm_api_key)
    assert "sk-test-123" not in repr(engine)


def test_base_url_passes_through_to_litellm():
    engine = build_dspy_engine(make_settings(llm_base_url="http://localhost:4000/v1"))  # type: ignore[arg-type]
    assert engine._lm.kwargs["api_base"] == "http://localhost:4000/v1"


def test_base_url_defaults_to_none():
    make = make_settings()
    print("\nmake llm_base_url:", repr(make.llm_base_url))
    engine = build_dspy_engine(make)
    print("engine kwargs api_base:", engine._lm.kwargs.get("api_base"))
    assert engine._lm.kwargs.get("api_base") is None
