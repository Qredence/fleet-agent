import pytest

from app.agent.signature import build_synthesizer
from app.kernel.run_input import validate_user_content


@pytest.mark.parametrize(
    "content", ["hello", [{"type": "text", "text": "file contents"}]]
)
def test_supported_text(content):
    validate_user_content(content)


@pytest.mark.parametrize(
    "content",
    [
        [{"type": "image", "url": "data:image/png;base64,AA"}],
        [{"type": "text", "text": "hello"}, {"type": "image", "url": "image.png"}],
        [{"type": "file"}],
        None,
    ],
)
def test_unsupported_content_is_rejected(content):
    with pytest.raises(ValueError, match="unsupported_input_type"):
        validate_user_content(content)


def test_synthesis_predictors_are_isolated():
    first, second = build_synthesizer(), build_synthesizer()
    first.set_lm(object())
    assert first is not second
    assert second.get_lm() is None


@pytest.mark.parametrize("mode", ["fixtures", "engine"])
@pytest.mark.parametrize("mixed", [False, True])
async def test_api_rejects_images_before_provider_or_reservation(
    mode, mixed, monkeypatch
):
    from httpx import ASGITransport, AsyncClient

    from tests.conftest import make_test_app
    from tests.test_agent_endpoint import run_input

    def forbidden(*args, **kwargs):
        pytest.fail("provider must not be constructed for unsupported input")

    monkeypatch.setattr("app.api.agent.parse_provider_override", forbidden)
    body = run_input()
    body["messages"][0]["content"] = (
        [{"type": "text", "text": "hello"}] if mixed else []
    ) + [{"type": "binary", "mimeType": "image/png", "data": "AA=="}]
    async with AsyncClient(
        transport=ASGITransport(app=make_test_app(agent_mode=mode)),
        base_url="http://test",
    ) as client:
        response = await client.post("/api/agent", json=body)
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "unsupported_input_type"


async def test_accepted_settlement_survives_client_cancellation():
    import asyncio

    from app.agui.run import _settle_terminal

    started, release = asyncio.Event(), asyncio.Event()
    committed = []

    async def commit():
        started.set()
        await release.wait()
        committed.append(True)
        return True

    task = asyncio.create_task(_settle_terminal(commit))
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert committed == [True]


async def test_settlement_retries_once():
    from app.agui.run import _settle_with_retry

    calls = []

    async def commit():
        calls.append(True)
        if len(calls) == 1:
            raise RuntimeError("temporary")
        return True

    assert await _settle_with_retry(commit)
    assert len(calls) == 2


async def test_overlapping_synthesis_keeps_provider_history_and_usage_isolated():
    import asyncio

    import dspy

    from app.agent.engine import AgentRunContext, DspyAgentEngine
    from app.agent.program import FleetAgent
    from tests.helpers.scripted_lm import ScriptedLM, router_call, synthesis_call

    programs = [FleetAgent(tool_profiles={"direct": []}) for _ in range(2)]
    models = [
        ScriptedLM([router_call("direct"), synthesis_call(answer=f"Answer {name}")])
        for name in ("A", "B")
    ]
    engines = [
        DspyAgentEngine(
            program_factory=lambda p=program: p, lm=model, adapter=dspy.JSONAdapter()
        )
        for program, model in zip(programs, models, strict=True)
    ]
    results = await asyncio.gather(
        *[
            engine.run(
                user_request=f"Question {name}",
                history=dspy.History(
                    messages=[
                        {"user_request": f"Prior {name}", "answer": f"History {name}"}
                    ]
                ),
                context=AgentRunContext(
                    thread_id=f"thread-{name}", run_id=f"run-{name}"
                ),
            )
            for engine, name in zip(engines, ("A", "B"), strict=True)
        ]
    )
    assert [r.answer for r in results] == ["Answer A", "Answer B"]
    assert all(r.usage["total_tokens"] == 30 for r in results)
    assert "History B" not in str(results[0].history)
    assert "History A" not in str(results[1].history)
    assert programs[0].synthesizer is not programs[1].synthesizer
