from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import dspy
import pytest
from ag_ui.core import Interrupt, ResumeEntry, RunAgentInput

from app.agent.approval import (
    ApprovalAwareReActV2,
    ApprovalRegistry,
)
from app.agent.callbacks import AgUiRunCallback
from app.agent.engine import AgentRunContext, DspyAgentEngine
from app.agent.factory import make_engine_builder
from app.agent.program import FleetAgent
from app.agent.provider import ProviderOverride
from app.agent.tool_registry import ToolMetadata
from app.agent.tooling import create_dspy_tool
from app.agui.event_bus import RunEventBus
from app.agui.live_coordinator import LiveDSPyCoordinator
from app.services.artifact_storage import LocalArtifactStorage
from app.settings import Settings
from tests.helpers.scripted_lm import ScriptedLM, submit_call


class RecordingLifecycle:
    def __init__(self) -> None:
        self.events: list[tuple[str, str]] = []

    def on_tool_start(
        self, call_id: str, instance: Any, inputs: dict[str, Any]
    ) -> None:
        del inputs
        self.events.append(("start", call_id))

    def on_tool_end(
        self,
        call_id: str,
        outputs: Any | None,
        exception: BaseException | None = None,
    ) -> None:
        del outputs, exception
        self.events.append(("end", call_id))

    def resume_tool_end(
        self,
        call_id: str,
        instance: Any,
        outputs: Any | None,
        exception: BaseException | None = None,
    ) -> None:
        del instance, outputs, exception
        self.events.append(("resume-end", call_id))


def _resume_entry(interrupt: Interrupt, approved: bool) -> ResumeEntry:
    return ResumeEntry.model_validate(
        {
            "interruptId": interrupt.id,
            "status": "resolved",
            "payload": {"approved": approved},
        }
    )


def _write_tool(calls: list[tuple[str, str]]) -> dspy.Tool:
    def write(path: str, content: str) -> str:
        """Write content to a test workspace."""
        calls.append((path, content))
        return "write completed"

    return create_dspy_tool(write, name="write")


def _make_engine(
    steps: list[Any],
    *,
    registry: ApprovalRegistry,
    lifecycle: RecordingLifecycle | None = None,
    provider_override: ProviderOverride | None = None,
    tool: dspy.Tool | None = None,
    approval_policy: dict[str, ToolMetadata | bool] | None = None,
) -> DspyAgentEngine:
    selected_tool = tool or _write_tool([])
    policy = approval_policy or {
        "write": ToolMetadata(
            name="write",
            capability="workspace_write",
            read_only=False,
            idempotent=False,
            parallelizable=False,
            requires_approval=True,
        )
    }

    def program_factory() -> FleetAgent:
        return FleetAgent(
            tools=[selected_tool],
            max_iters=4,
            approval_policy=policy,
            lifecycle=lifecycle,
        )

    return DspyAgentEngine(
        program_factory=program_factory,
        lm=ScriptedLM(steps),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(),
        approval_registry=registry,
        provider_override=provider_override,
        lifecycle=lifecycle,
    )


def _context(
    *, thread_id: str = "thread-approval", run_id: str = "run-approval"
) -> AgentRunContext:
    return AgentRunContext(
        thread_id=thread_id,
        run_id=run_id,
        assistant_message_id="assistant-approval",
    )


async def test_gated_tool_has_no_side_effect_until_approval_and_runs_once() -> None:
    calls: list[tuple[str, str]] = []
    registry = ApprovalRegistry()
    lifecycle = RecordingLifecycle()
    engine = _make_engine(
        [
            [{"name": "write", "args": {"path": "notes.txt", "content": "secret"}}],
            [submit_call(answer="saved")],
        ],
        registry=registry,
        lifecycle=lifecycle,
        tool=_write_tool(calls),
    )

    first = await engine.run(
        user_request="save this",
        history=None,
        context=_context(),
    )

    assert first.status == "interrupted"
    assert first.termination_reason == "approval_required"
    assert calls == []
    assert len(first.interrupts) == 1
    interrupt = first.interrupts[0]
    public_interrupt = json.dumps(interrupt.model_dump(mode="json"))
    # The interrupt carries a bounded, single-line preview naming the gated
    # action's target, while the argument values (the file content) stay
    # server-side and never reach the browser.
    assert interrupt.metadata == {
        "toolName": "write",
        "action": "approval_required",
        "toolPreview": "write notes.txt (6 chars)",
    }
    assert "secret" not in public_interrupt
    assert interrupt.reason == "tool_call"
    assert lifecycle.events == [("start", interrupt.tool_call_id or "")]

    resumed = await engine.run(
        user_request="save this",
        history=None,
        context=_context(run_id="run-approval-resume"),
        resume=[_resume_entry(interrupt, True)],
    )

    assert resumed.status == "completed"
    assert resumed.answer == "saved"
    assert calls == [("notes.txt", "secret")]
    assert lifecycle.events == [
        ("start", interrupt.tool_call_id or ""),
        ("resume-end", interrupt.tool_call_id or ""),
    ]


async def test_denial_is_a_safe_failure_and_agent_continues() -> None:
    calls: list[tuple[str, str]] = []
    registry = ApprovalRegistry()
    engine = _make_engine(
        [
            [{"name": "write", "args": {"path": "denied.txt", "content": "x"}}],
            [submit_call(answer="continued")],
        ],
        registry=registry,
        tool=_write_tool(calls),
    )

    first = await engine.run(
        user_request="save this",
        history=None,
        context=_context(),
    )
    resumed = await engine.run(
        user_request="save this",
        history=None,
        context=_context(run_id="run-denied-resume"),
        resume=[_resume_entry(first.interrupts[0], False)],
    )

    assert resumed.status == "completed"
    assert resumed.answer == "continued"
    assert calls == []


async def test_duplicate_expired_wrong_thread_missing_provider_and_restart_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []
    clock = [100.0]
    monkeypatch.setattr("app.agent.approval.time.monotonic", lambda: clock[0])
    registry = ApprovalRegistry(ttl_seconds=5)
    provider = ProviderOverride(api_key="sk-or-original", model="vendor/model")
    engine = _make_engine(
        [[{"name": "write", "args": {"path": "x", "content": "y"}}], submit_call()],
        registry=registry,
        provider_override=provider,
        tool=_write_tool(calls),
    )
    first = await engine.run(
        user_request="save",
        history=None,
        context=_context(),
    )
    interrupt = first.interrupts[0]
    entry = _resume_entry(interrupt, True)

    wrong_thread = await engine.run(
        user_request="save",
        history=None,
        context=_context(thread_id="other-thread", run_id="wrong-thread"),
        resume=[entry],
    )
    assert wrong_thread.status == "failed"
    assert wrong_thread.error_code == "approval_invalid"
    assert calls == []

    wrong_provider = _make_engine(
        [],
        registry=registry,
        provider_override=ProviderOverride(api_key="sk-or-other"),
        tool=_write_tool(calls),
    )
    invalid_provider = await wrong_provider.run(
        user_request="save",
        history=None,
        context=_context(run_id="wrong-provider"),
        resume=[entry],
    )
    assert invalid_provider.error_code == "approval_invalid"
    assert calls == []

    missing_credentials = _make_engine([], registry=registry, tool=_write_tool(calls))
    invalid_credentials = await missing_credentials.run(
        user_request="save",
        history=None,
        context=_context(run_id="missing-credentials"),
        resume=[entry],
    )
    assert invalid_credentials.error_code == "approval_invalid"
    assert calls == []

    clock[0] = 106.0
    expired = await engine.run(
        user_request="save",
        history=None,
        context=_context(run_id="expired"),
        resume=[entry],
    )
    assert expired.error_code == "approval_expired"
    assert calls == []

    # A fresh process has an empty in-memory registry; a previously issued
    # interrupt must not be recoverable after this explicit restart cleanup.
    registry.clear()
    restarted = await engine.run(
        user_request="save",
        history=None,
        context=_context(run_id="restarted"),
        resume=[entry],
    )
    assert restarted.error_code == "approval_invalid"
    assert calls == []


async def test_read_only_tool_is_not_interrupted() -> None:
    calls: list[str] = []

    def read(query: str) -> str:
        """Read a test value."""
        calls.append(query)
        return "read result"

    tool = create_dspy_tool(read, name="read")
    registry = ApprovalRegistry()
    engine = _make_engine(
        [
            [{"name": "read", "args": {"query": "state"}}],
            [submit_call(answer="done")],
        ],
        registry=registry,
        tool=tool,
        approval_policy={
            "read": ToolMetadata(
                name="read",
                capability="workspace_read",
                read_only=True,
                requires_approval=False,
            )
        },
    )

    result = await engine.run(
        user_request="read this",
        history=None,
        context=_context(),
    )

    assert result.status == "completed"
    assert result.interrupts == []
    assert calls == ["state"]


async def test_coordinator_uses_native_interrupt_and_stable_resume_ids() -> None:
    calls: list[tuple[str, str]] = []
    registry = ApprovalRegistry()
    tool = _write_tool(calls)

    def builder_factory(steps: list[Any]) -> Callable[..., DspyAgentEngine]:
        def builder(bus: RunEventBus, *, thread_id: str) -> DspyAgentEngine:
            del thread_id
            lifecycle = AgUiRunCallback(bus=bus, cancel_token=bus.cancel_token)
            return _make_engine(
                steps,
                registry=registry,
                tool=tool,
                lifecycle=lifecycle,
            )

        return builder

    def make_input(run_id: str, messages: list[dict[str, Any]], resume=None):
        payload: dict[str, Any] = {
            "threadId": "thread-approval",
            "runId": run_id,
            "state": None,
            "messages": messages,
            "tools": [],
            "context": [],
            "forwardedProps": None,
        }
        if resume is not None:
            payload["resume"] = [item.model_dump(by_alias=True) for item in resume]
        return RunAgentInput.model_validate(payload)

    first_messages = [{"id": "user-approval", "role": "user", "content": "save"}]
    first_stream = LiveDSPyCoordinator().stream(
        input_data=make_input(
            "run-approval-coordinator",
            first_messages,
        ),
        engine_builder=builder_factory(
            [[{"name": "write", "args": {"path": "private.txt", "content": "secret"}}]]
        ),
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
    )
    first_events = [
        json.loads(chunk.removeprefix("data: ").strip()) async for chunk in first_stream
    ]
    first_interrupt = next(
        event["outcome"]["interrupts"][0]
        for event in first_events
        if event["type"] == "RUN_FINISHED"
    )
    first_tool_result = [
        event for event in first_events if event["type"] == "TOOL_CALL_RESULT"
    ]
    assert first_events[-1]["outcome"]["type"] == "interrupt"
    assert first_tool_result == []
    # The interrupt's bounded preview names the gated write target, but the
    # argument values (the file content) never reach the browser.
    assert "write private.txt (6 chars)" in json.dumps(first_events)
    assert "secret" not in json.dumps(first_events)

    assistant = {
        "id": "msg-run-approval-coordinator",
        "role": "assistant",
        "content": "Approval is pending.",
    }
    resume = ResumeEntry.model_validate(
        {
            "interruptId": first_interrupt["id"],
            "status": "resolved",
            "payload": {"approved": True},
        }
    )
    # The no-persistence coordinator derives its assistant id from the
    # previous stream's fallback id; use that exact id for the native resume.
    assistant["id"] = "msg-run-approval-coordinator"
    second_stream = LiveDSPyCoordinator().stream(
        input_data=make_input(
            "run-approval-coordinator-resume",
            [*first_messages, assistant],
            [resume],
        ),
        engine_builder=builder_factory([[submit_call(answer="saved")]]),
        accept="text/event-stream",
        is_disconnected=lambda: _false(),
    )
    second_events = [
        json.loads(chunk.removeprefix("data: ").strip())
        async for chunk in second_stream
    ]

    assert second_events[-1]["type"] == "RUN_FINISHED"
    assert "RUN_ERROR" not in [event["type"] for event in second_events]
    result_events = [
        event for event in second_events if event["type"] == "TOOL_CALL_RESULT"
    ]
    assert len(result_events) == 1
    assert result_events[0]["toolCallId"] == first_interrupt["toolCallId"]
    assert [
        event["messageId"]
        for event in second_events
        if event["type"] == "TEXT_MESSAGE_START"
    ] == ["msg-run-approval-coordinator"]
    assert calls == [("private.txt", "secret")]


async def _false() -> bool:
    return False


def test_flex_mutating_path_uses_approval_aware_program(tmp_path) -> None:
    settings = Settings(
        reasoning_program="flex",
        flex_enabled=True,
        flex_allow_mutating_tools=True,
        workspace_root=str(tmp_path),
        workspace_write_tools_enabled=True,
        workspace_bash_tool_enabled=True,
        llm_api_key=None,
    )
    loop = asyncio.new_event_loop()
    try:
        builder = make_engine_builder(
            settings,
            storage=LocalArtifactStorage(tmp_path / "artifacts"),
        )
        engine = builder(RunEventBus(loop), thread_id="thread-flex")
        program = engine._program_factory()  # type: ignore[attr-defined]
    finally:
        loop.close()

    assert isinstance(program, FleetAgent)
    assert isinstance(program.workspace_write_agent, ApprovalAwareReActV2)
    assert isinstance(program.workspace_shell_agent, ApprovalAwareReActV2)


def test_pinned_private_react_v2_symbols_exist() -> None:
    """approval.py forks ReActV2 through private dspy 3.3.1 internals.

    The approval loop breaks at import time if a dspy bump renames these
    helpers, so this guard turns silent contract drift into a loud failure
    before the version pin is relaxed.
    """
    import inspect

    from dspy.predict import react_v2

    for symbol in (
        "_append_history_event",
        "_coerce_history",
        "_coerce_tool_calls",
        "_ensure_tool_call_ids",
        "AdapterParseError",
        "ContextWindowExceededError",
        "ToolCallResults",
        "ToolCalls",
        "format_error_for_lm",
    ):
        assert hasattr(react_v2, symbol), symbol

    ensure = inspect.signature(react_v2._ensure_tool_call_ids)
    assert len(ensure.parameters) == 2


def test_checkpoint_serde_roundtrip_preserves_hidden_state() -> None:
    """The persisted JSON form must carry every field the resume loop reads.

    This is the contract the DB-backed registry depends on: ToolCall ids in
    particular are dropped by ``ToolCalls.model_dump``, so they are stored
    explicitly; the prediction reduces to ``next_thought`` because that is
    the only prediction surface ``_history_event`` reads.
    """
    from app.agent.approval import (
        ApprovalCheckpoint,
        checkpoint_from_json,
        checkpoint_to_json,
    )

    history = dspy.History(
        messages=[
            {"role": "user", "content": "save this"},
            {
                "role": "assistant",
                "content": "Working on it.",
                "tool_calls": {
                    "tool_calls": [
                        {"id": "call_0_0", "name": "write", "args": {"path": "f.txt"}}
                    ],
                    "tool_call_results": [],
                },
            },
        ]
    )
    checkpoint = ApprovalCheckpoint(
        profile_name="workspace_write_agent",
        history=history,
        pending_inputs={"user_request": "save this"},
        prediction=dspy.Prediction(next_thought="working"),
        tool_calls=dspy.ToolCalls(
            tool_calls=[
                dspy.ToolCalls.ToolCall(
                    id="call_0_0", name="write", args={"path": "f.txt", "content": "s"}
                )
            ]
        ),
        values=(),
        errors=(),
        next_index=0,
        turn_index=0,
        tool_name="write",
        tool_call_id="call_0_0",
        assistant_message_id="assistant-serde",
    )

    data = checkpoint_to_json(checkpoint)
    assert data["schemaVersion"] == 1
    # Tool-call ids survive serialization even though model_dump drops them.
    assert data["toolCalls"][0]["id"] == "call_0_0"

    restored = checkpoint_from_json(data)
    assert restored.profile_name == checkpoint.profile_name
    assert restored.tool_call_id == "call_0_0"
    assert [call.id for call in restored.tool_calls.tool_calls] == ["call_0_0"]
    assert restored.tool_calls.tool_calls[0].args == {
        "path": "f.txt",
        "content": "s",
    }
    assert restored.pending_inputs == {"user_request": "save this"}
    assert restored.prediction.next_thought is not None
    assert restored.next_index == 0
    assert restored.turn_index == 0
    assert restored.tool_name == "write"
    assert restored.assistant_message_id == "assistant-serde"
    assert restored.history.messages[0]["role"] == "user"
    assert (
        restored.history.messages[1]["tool_calls"]["tool_calls"][0]["id"] == "call_0_0"
    )

    # The JSON form stays JSON-clean (safe for a JSONB column round trip).
    json.dumps(data)

    # Corrupt or future rows fail closed instead of resuming garbage.
    with pytest.raises(ValueError):
        checkpoint_from_json({**data, "schemaVersion": 99})
    with pytest.raises(ValueError):
        checkpoint_from_json({k: v for k, v in data.items() if k != "toolName"})


def test_registry_protocol_shape_is_stable() -> None:
    """Both registry implementations satisfy the engine's protocol seam."""
    from app.agent.approval import ApprovalRegistry, ApprovalRegistryProtocol
    from app.services.durable_approvals import DurableApprovalRegistry

    assert issubclass(ApprovalRegistry, ApprovalRegistryProtocol)
    assert issubclass(DurableApprovalRegistry, ApprovalRegistryProtocol)
