"""Optional live smoke test — runs ONLY when FLEET_AGENT_LLM_API_KEY is set.

Never part of normal CI: unit tests use ScriptedLM. This exists so a developer
can verify the real OpenAI wiring with:
    FLEET_AGENT_LLM_API_KEY=sk-... uv run pytest tests/test_engine_live.py
"""

import os

import pytest

from app.agent.engine import AgentRunContext
from app.agent.factory import build_dspy_engine
from app.settings import get_settings

pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_ENGINE_LIVE_TEST"),
    reason="requires RUN_ENGINE_LIVE_TEST=1 plus FLEET_AGENT_LLM_* env: "
    "RUN_ENGINE_LIVE_TEST=1 uv run pytest tests/test_engine_live.py -s",
)


async def test_live_engine_simple_question():
    get_settings.cache_clear()
    engine = build_dspy_engine(get_settings())
    result = await engine.run(
        user_request="What does STATE_DELTA contain? Answer in one short sentence.",
        history=None,
        context=AgentRunContext(thread_id="t-live", run_id="r-live"),
    )

    assert result.status == "completed"
    assert result.answer
    assert result.termination_reason in {"submit", "forced_submit"}
    assert result.error_code is None
    assert result.usage.get("total_tokens", 0) > 0
