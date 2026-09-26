"""Live-run DSPy tracing must actually produce MLflow traces.

Regression guard for the callbacks-composition bug: ``dspy.context(callbacks=[...])``
REPLACES ``dspy.settings.callbacks`` instead of extending it, so passing only the
engine's own callbacks silently discarded the callback that ``mlflow.dspy.autolog``
installs. Tracing looked wired and produced zero traces on every live run.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import dspy
import pytest
from dspy.utils.callback import BaseCallback
from dspy.utils.dummies import DummyLM

from app.agent.engine import AgentRunContext, DspyAgentEngine, compose_callbacks
from app.services.mlflow_observability import (
    TRACING_EXPERIMENT,
    configure_mlflow,
    redact_span_secrets,
)
from app.settings import Settings


class _Answer(dspy.Signature):
    """Answer the request."""

    user_request: str = dspy.InputField()
    answer: str = dspy.OutputField()


class _TinyProgram(dspy.Module):
    """The smallest program the engine boundary accepts."""

    def __init__(self) -> None:
        super().__init__()
        self.answer = dspy.Predict(_Answer)

    def forward(self, *, user_request: str, history: object = None) -> dspy.Prediction:
        return self.answer(user_request=user_request)


def _trace_count(db_path: Path) -> int:
    """Read the trace count straight from the tracking store."""
    import mlflow

    mlflow.flush_trace_async_logging()
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        row = connection.execute("select count(*) from trace_info").fetchone()
    finally:
        connection.close()
    return int(row[0])


@pytest.fixture()
def tracing_store(tmp_path: Path) -> Iterator[Path]:
    """Enable dspy tracing into a throwaway sqlite store, then fully disable it.

    Tracing is global (autolog mutates ``dspy.settings.callbacks``), so the teardown
    must restore both the callbacks list and the tracking URI or later tests inherit
    a store that no longer exists.
    """
    import mlflow

    db_path = tmp_path / "tracing.db"
    dspy.settings.configure(callbacks=[])
    assert (
        configure_mlflow(
            Settings(
                mlflow_tracing_enabled=True,
                mlflow_tracking_uri=f"sqlite:///{db_path}",
            )
        )
        is True
    )
    try:
        yield db_path
    finally:
        mlflow.dspy.autolog(disable=True)
        dspy.settings.configure(callbacks=[])
        mlflow.set_tracking_uri(f"sqlite:///{tmp_path}/after-teardown.db")


def test_compose_callbacks_extends_dspy_callbacks() -> None:
    """The engine must layer its callbacks on top of DSPy's, never replace them."""

    class _Existing(BaseCallback):
        pass

    class _Own(BaseCallback):
        pass

    existing, own = _Existing(), _Own()
    with dspy.context(callbacks=[existing]):
        composed = compose_callbacks(_TinyProgram(), [own])

    assert existing in composed, "DSPy's active callbacks were dropped"
    assert own in composed, "the engine's own callbacks were dropped"
    assert composed.index(existing) < composed.index(own)


def test_dspy_context_callbacks_replaces_rather_than_extends() -> None:
    """Document WHY compose_callbacks exists (pins dspy 3.4.0 semantics).

    If a future DSPy switches ``context(callbacks=...)`` to extend, this tripwire
    fails and ``compose_callbacks`` can be simplified back to a plain assignment.
    """

    class _Outer(BaseCallback):
        pass

    class _Inner(BaseCallback):
        pass

    outer, inner = _Outer(), _Inner()
    with dspy.context(callbacks=[outer]):
        with dspy.context(callbacks=[inner]):
            assert dspy.settings.callbacks == [inner]
        assert dspy.settings.callbacks == [outer]


def test_application_tool_lifecycle_program_keeps_dspy_callbacks() -> None:
    """A program owning its tool lifecycle still gets DSPy's callbacks."""

    class _Existing(BaseCallback):
        pass

    class _OwnLifecycle(_TinyProgram):
        application_tool_lifecycle = True

    existing = _Existing()
    with dspy.context(callbacks=[existing]):
        composed = compose_callbacks(_OwnLifecycle(), [])

    assert composed == [existing]


async def test_engine_run_lands_a_trace(tracing_store: Path) -> None:
    """A real engine run must produce at least one trace in the tracing experiment."""
    import mlflow

    assert _trace_count(tracing_store) == 0, "store must start empty"

    engine = DspyAgentEngine(
        program_factory=_TinyProgram,
        lm=DummyLM([{"answer": "traced"} for _ in range(5)]),
        adapter=dspy.ChatAdapter(),
    )
    result = await engine.run(
        user_request="hello",
        history=None,
        context=AgentRunContext(thread_id="thread-trace", run_id="run-trace"),
    )

    assert result.status == "completed"
    assert result.answer == "traced"
    experiment = mlflow.get_experiment_by_name(TRACING_EXPERIMENT)
    assert experiment is not None, "configure_mlflow must create the tracing experiment"
    assert _trace_count(tracing_store) >= 1, "the run produced no trace"


def test_redact_span_secrets_preserves_structure_with_sensitive_keys() -> None:
    """Span secret redaction must not corrupt JSON structures containing credentials."""
    from unittest.mock import MagicMock

    span = MagicMock()
    span.inputs = {
        "user_request": "here is my token: sk-ant-api03-1234567890abcdef12345",
        "kwargs": {
            "api_key": "1234567890abcdef1234567890",
            "count": 42,
            "nested": {"password": "secretpassword123"},
        },
    }
    span.outputs = {"result": "success", "secret": "confidential1234567"}
    span.attributes = {
        "tag": "safe",
        "detail": "token: ghp_1234567890abcdef1234567890",
    }

    redact_span_secrets(span)

    assert span.set_inputs.called
    inputs = span.set_inputs.call_args[0][0]
    assert "[redacted]" in inputs["user_request"]
    assert inputs["kwargs"]["api_key"] == "[redacted]"
    assert inputs["kwargs"]["count"] == 42
    assert inputs["kwargs"]["nested"]["password"] == "[redacted]"

    assert span.set_outputs.called
    outputs = span.set_outputs.call_args[0][0]
    assert outputs["result"] == "success"
    assert outputs["secret"] == "[redacted]"

    assert span.set_attribute.called
    span.set_attribute.assert_called_with("detail", "token: [redacted]")
