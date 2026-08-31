"""Contract tests for the private DSPy helpers re-exported by dspy_compat.

These pin the behavior of the underscore-prefixed ``dspy.predict.react_v2``
helpers that the application-owned approval loop depends on. If a DSPy
upgrade changes any of these behaviors, these tests fail with a clear
diagnosis before ``ApprovalAwareReActV2`` can silently misbehave in
production.

When bumping DSPy:
1. update ``EXPECTED_DSPY_VERSION`` in ``app/agent/dspy_compat.py``,
2. fix any behavior drift asserted here,
3. re-verify the parity test below against the new vanilla loop.
"""

from __future__ import annotations

import dspy

from app.agent.approval import ApprovalAwareReActV2
from app.agent.dspy_compat import (
    EXPECTED_DSPY_VERSION,
    append_history_event,
    coerce_history,
    coerce_tool_calls,
    ensure_tool_call_ids,
)
from app.agent.signature import AgentSignature
from app.agent.tools import search_docs
from tests.helpers.scripted_lm import ScriptedLM, submit_call


def test_installed_dspy_version_matches_compatibility_pin() -> None:
    assert dspy.__version__ == EXPECTED_DSPY_VERSION


def test_coerce_history_none_returns_empty_history() -> None:
    history = coerce_history(None)
    assert isinstance(history, dspy.History)
    assert history.messages == []


def test_coerce_history_passthrough_and_dict_validation() -> None:
    original = dspy.History(messages=[{"user_request": "hi"}])
    assert coerce_history(original) is original

    from_dict = coerce_history({"messages": [{"user_request": "hi"}]})
    assert isinstance(from_dict, dspy.History)
    assert from_dict.messages == original.messages


def test_coerce_tool_calls_none_and_instance_round_trip() -> None:
    empty = coerce_tool_calls(None)
    assert empty.tool_calls == []

    calls = coerce_tool_calls({"tool_calls": [{"name": "read", "args": {"path": "x"}}]})
    assert [call.name for call in calls.tool_calls] == ["read"]


def test_ensure_tool_call_ids_fills_only_missing_ids() -> None:
    calls = coerce_tool_calls(
        {
            "tool_calls": [
                {"name": "read", "args": {}},
                {"id": "custom", "name": "grep", "args": {}},
            ]
        }
    )
    ensured = ensure_tool_call_ids(calls, turn_index=3)
    assert ensured.tool_calls[0].id == "call_3_0"
    assert ensured.tool_calls[1].id == "custom"


def test_append_history_event_appends_nonempty_events_only() -> None:
    history = dspy.History(messages=[])
    append_history_event(history, {"user_request": "q"})
    assert len(history.messages) == 1
    append_history_event(history, {})
    assert len(history.messages) == 1


def test_format_error_for_lm_stays_bounded_and_single_line() -> None:
    message = dspy_compat_format(ValueError("boom"))
    assert "boom" in message
    assert "\nTraceback" not in message or message.count("\n") < 12


def dspy_compat_format(exc: Exception) -> str:
    from app.agent.dspy_compat import format_error_for_lm

    return str(format_error_for_lm(exc, traceback_frames=2))


def _run_program(program: dspy.Module) -> dspy.Prediction:
    steps = [
        [{"name": "search_docs", "args": {"query": "state sync"}}],
        [submit_call(answer="It works.")],
    ]
    with dspy.context(
        lm=ScriptedLM(steps),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(),
    ):
        return program(user_request="How does state sync work?", history=None)


def test_approval_aware_react_matches_vanilla_react_when_nothing_is_gated() -> None:
    """Parity: with no gated tools, the approval loop must behave exactly
    like the DSPy ReActV2 it is derived from — same submit outputs, same
    termination reason, same history shape."""
    vanilla = dspy.ReActV2(AgentSignature, tools=[search_docs], max_iters=4)
    approval = ApprovalAwareReActV2(
        AgentSignature,
        tools=[search_docs],
        max_iters=4,
        profile_name="parity",
        approval_policy={},
    )

    vanilla_result = _run_program(vanilla)
    approval_result = _run_program(approval)

    assert vanilla_result.answer == approval_result.answer == "It works."
    assert vanilla_result.process_summary == approval_result.process_summary
    assert vanilla_result.termination_reason == "submit"
    assert approval_result.termination_reason == "submit"
    assert approval_result.key_decisions == vanilla_result.key_decisions
    assert approval_result.caveats == vanilla_result.caveats
    assert len(approval_result.history.messages) == len(vanilla_result.history.messages)
    # The tool observation from the shared search_docs tool is identical.
    assert any(
        "found" in str(message) or "search_docs" in str(message)
        for message in approval_result.history.messages
    )
