"""First-class, capability-routed DSPy program for Fleet Agent."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

import dspy
from dspy.utils.exceptions import AdapterParseError, ContextWindowExceededError

from app.agent.engine import _reason_from_react_exc
from app.agent.evidence import DEFAULT_MAX_CHARS, bounded_json
from app.agent.routing import ROUTES, ToolRoute, coerce_route, routing_signature
from app.agent.signature import (
    SYNTHESIS_STREAM_FIELDS,
    build_gatherer,
    build_synthesizer,
)
from app.agent.tool_registry import TOOL_SPECS
from app.agent.tooling import RESERVED_TOOL_NAMES, create_dspy_tool, is_async_tool

logger = logging.getLogger(__name__)

_MAX_EVIDENCE_CHARS = DEFAULT_MAX_CHARS


class FleetAgent(dspy.Module):  # type: ignore[misc]  # DSPy is untyped
    """Route each request into a least-privileged evidence-gathering profile.

    ``tool_profiles`` is the capability lattice: one entry per route holding
    exactly the ``dspy.Tool`` objects that route may call. The program builds
    one ``dspy.ReActV2`` per route, so a run can never reach a tool outside the
    profile the router selected. Tools that require approval are filtered out of
    every profile before the program is built, so the model never sees them
    unless the run authorized them up front.

    Those agents gather evidence only. The ``synthesizer`` writes the public
    fields from that evidence, and that split is what makes DSPy-native
    streaming possible: ``answer`` and ``process_summary`` are predictor
    output fields, so ``dspy.streamify`` can stream them, which is not true
    of values carried inside a ``submit`` tool call.
    """

    def __init__(
        self,
        *,
        tool_profiles: Mapping[ToolRoute, Sequence[dspy.Tool]],
        max_iters: int = 20,
        router_instructions: str | None = None,
    ) -> None:
        super().__init__()
        if max_iters < 1:
            raise ValueError("max_iters must be at least 1")
        # Promoted instructions come from an offline optimizer artifact; unset
        # keeps the baseline contract declared in routing.py.
        self.router = dspy.Predict(routing_signature(router_instructions))
        profiles = {
            route: [
                tool
                for tool in _validate_tools(tool_profiles.get(route, ()))
                if tool.name != "write_report"
            ]
            for route in ROUTES
        }
        self.tool_names = {
            route: tuple(str(tool.name) for tool in tools)
            for route, tools in profiles.items()
        }
        # prompts/evidence.md builds one ReActV2 node per least-privilege
        # profile, each carrying that profile's tools only.
        #
        # A profile with no tools has nothing to gather - ``direct`` answers from
        # the model's own knowledge - so it gets no loop at all rather than an LM
        # call that can only decide to stop.
        self.evidence_agents = {
            route: build_gatherer(tools, max_iters=max_iters)
            for route, tools in profiles.items()
            if tools
        }
        # Built from prompts/synthesize.md over the gathered evidence.
        self.synthesizer = build_synthesizer()
        self.synthesis_stream_fields = SYNTHESIS_STREAM_FIELDS

    def forward(
        self,
        *,
        user_request: str,
        history: dspy.History | dict[str, Any] | None = None,
    ) -> dspy.Prediction:
        """Gather evidence in the selected profile, then write public fields."""
        if not user_request.strip():
            raise ValueError("user_request must not be empty")

        incoming_history: dspy.History
        if isinstance(history, dict):
            incoming_history = dspy.History.model_validate(history)
        elif isinstance(history, dspy.History):
            incoming_history = history
        else:
            incoming_history = dspy.History(messages=[])

        conversation_history = dspy.History(
            messages=_extract_conversation_turns(incoming_history)
        )

        prior_count = len(incoming_history.messages)
        route, output_intent, routing_valid = self._select_decision(
            user_request, conversation_history
        )
        evidence_reason = "submit"
        evidence_status = "complete" if routing_valid else "insufficient"
        gatherer = self.evidence_agents.get(route)
        essential = {
            "workspace_read": "workspace_read",
            "workspace_write": "workspace_write",
            "workspace_shell": "shell",
        }.get(route)
        capability_missing = (route != "direct" and gatherer is None) or (
            essential is not None
            and not any(
                TOOL_SPECS[name].capability == essential
                for name in self.tool_names[route]
                if name in TOOL_SPECS
            )
        )
        # With no loop to run, the prior turns ARE the evidence: a follow-up that
        # routes to ``direct`` still has to synthesize from what earlier turns
        # gathered, so the incoming history is used as-is.
        evidence_history = incoming_history
        if gatherer is not None:
            # DSPy 3.4 ReActV2 makes one forced-submit LM call when the loop ends
            # without ``submit``, and it raises when that call fails. ReActV2
            # mutates the passed dspy.History in place, so the failed attempt's
            # partial tool turns are already in incoming_history; mapping here -
            # the one program boundary - keeps that history without any
            # engine-side hook into DSPy internals.
            try:
                evidence = gatherer(user_request=user_request, history=incoming_history)
            except (
                ValueError,
                AdapterParseError,
                ContextWindowExceededError,
            ) as exc:
                reason = _reason_from_react_exc(exc) or "failed"
                if reason == "failed":
                    raise
                evidence_history = incoming_history
                evidence_reason = reason
                evidence_status = (
                    "partial"
                    if len(incoming_history.messages) > prior_count
                    else "insufficient"
                )
            else:
                evidence_reason = str(getattr(evidence, "termination_reason", "submit"))
                if evidence_reason not in {
                    "submit",
                    "evidence_submit",
                    "forced_submit",
                    "max_iters",
                    "timeout",
                    "cancelled",
                    "context_window_exceeded",
                    "parse_error",
                }:
                    evidence_reason = "failed"
                if evidence_reason not in {"submit", "evidence_submit"}:
                    evidence_status = "partial"
                evidence_history = getattr(evidence, "history", incoming_history)

        if capability_missing:
            evidence_status, evidence_reason = "insufficient", "capability_unavailable"
        synthesis = self._synthesize(
            user_request=user_request,
            evidence_history=evidence_history,
            conversation_history=conversation_history,
            evidence_outcome={"status": evidence_status, "reason": evidence_reason},
            output_intent=output_intent,
            current_run_start=prior_count,
        )

        ans = getattr(synthesis, "answer", None)
        summary = getattr(synthesis, "process_summary", None)
        decisions = list(getattr(synthesis, "key_decisions", None) or [])
        caveats = list(getattr(synthesis, "caveats", None) or [])
        if evidence_status != "complete":
            caveats.append(
                "Evidence collection was incomplete; "
                "external verification may be limited."
            )
        if not routing_valid:
            caveats.append(
                "Capability selection failed safely; "
                "no additional tools were authorized."
            )

        history_msgs = (
            getattr(evidence_history, "messages", None)
            if isinstance(evidence_history, dspy.History)
            else None
        )
        if (
            gatherer is not None
            and isinstance(history_msgs, list)
            and len(history_msgs) > 0
        ):
            # Evidence loop produced tool messages; attach synthesized answer
            history_msgs[-1]["answer"] = ans
            if summary:
                history_msgs[-1]["process_summary"] = summary
            if decisions:
                history_msgs[-1]["key_decisions"] = decisions
            if caveats:
                history_msgs[-1]["caveats"] = caveats
            final_history = evidence_history
        else:
            # Direct / tool-free turn: append this turn to conversation history
            turn_msg: dict[str, Any] = {
                "user_request": user_request,
                "answer": ans,
                "process_summary": summary,
                "key_decisions": decisions,
                "caveats": caveats,
            }
            output_messages = list(getattr(incoming_history, "messages", None) or [])
            output_messages.append(turn_msg)
            final_history = dspy.History(messages=output_messages)

        result = dspy.Prediction(
            answer=ans,
            process_summary=summary,
            key_decisions=decisions,
            caveats=caveats,
            history=final_history,
            termination_reason="synthesis",
            evidence_status=evidence_status,
            evidence_reason=evidence_reason,
            output_intent=output_intent,
            routing_valid=routing_valid,
        )
        # Diagnostic metadata stays on the server-side Prediction and is not
        # included in AgentRunResult or any AG-UI event.
        result.agent_route = route
        logger.info(
            "agent routed",
            extra={"route": route, "tool_names": list(self.tool_names[route])},
        )
        return result

    def _select_route(self, user_request: str) -> ToolRoute:
        return self._select_decision(user_request, dspy.History(messages=[]))[0]

    def _select_decision(
        self, user_request: str, history: dspy.History
    ) -> tuple[ToolRoute, str, bool]:
        context = bounded_json(list(reversed(history.messages[-6:])), max_chars=4000)
        try:
            decision = self.router(
                user_request=user_request, conversation_context=context
            )
        except (AdapterParseError, ValueError):
            return "direct", "none", False
        raw = getattr(decision, "route", None)
        route = coerce_route(raw)
        valid = (
            isinstance(raw, str)
            and raw.strip().strip("\"'`").lower().replace("-", "_").replace(" ", "_")
            in ROUTES
        )
        output = getattr(decision, "output_intent", "none")
        valid = valid and output in {"none", "managed_report"}
        if route == "artifact":
            output = "managed_report"
        return (
            route,
            "managed_report" if valid and output == "managed_report" else "none",
            valid,
        )

    def _synthesize(
        self,
        *,
        user_request: str,
        evidence_history: dspy.History | None = None,
        conversation_history: dspy.History | None = None,
        history: dspy.History | None = None,
        evidence_outcome: dict[str, str] | None = None,
        output_intent: str = "none",
        current_run_start: int | None = None,
    ) -> dspy.Prediction:
        """Write the public fields from the evidence the loop gathered.

        The synthesis call runs under ChatAdapter: its section markers give
        StreamListener exact, boilerplate-free field boundaries, while the
        evidence loop keeps the caller-configured JSONAdapter for tool
        calling.  This local adapter scope is invisible to the stream
        consumer task, so the engine's listeners pin the same adapter when
        parsing chunks.
        """
        ev_hist = evidence_history if evidence_history is not None else history
        conv_hist = conversation_history
        if conv_hist is None and ev_hist is not None:
            conv_hist = dspy.History(messages=_extract_conversation_turns(ev_hist))
        history_arg = conv_hist or dspy.History(messages=[])
        evidence_json = _evidence_json(ev_hist, current_run_start=current_run_start)
        if evidence_outcome and evidence_outcome["status"] != "complete":
            evidence_json = bounded_json(
                [
                    {
                        "tool": "evidence_outcome",
                        "result": evidence_outcome,
                        "is_error": True,
                    },
                    *json.loads(evidence_json),
                ],
                max_chars=_MAX_EVIDENCE_CHARS,
            )
        with dspy.context(adapter=dspy.ChatAdapter()):
            return self.synthesizer(
                user_request=user_request,
                evidence_json=evidence_json,
                output_intent=output_intent,
                history=history_arg,
            )


def _extract_conversation_turns(history: dspy.History | None) -> list[dict[str, Any]]:
    """Extract prior user and assistant turns for DSPy ChatAdapter context."""
    if history is None:
        return []
    turns: list[dict[str, Any]] = []
    current_req: str | None = None
    for msg in getattr(history, "messages", None) or []:
        if isinstance(msg, dict):
            req = msg.get("user_request")
            ans = msg.get("answer")
            summary = msg.get("process_summary")
        else:
            req = getattr(msg, "user_request", None)
            ans = getattr(msg, "answer", None)
            summary = getattr(msg, "process_summary", None)

        if req and ans:
            item: dict[str, Any] = {"user_request": req, "answer": ans}
            if summary:
                item["process_summary"] = summary
            turns.append(item)
            current_req = None
        elif req and not ans:
            current_req = req
        elif ans and current_req:
            item = {"user_request": current_req, "answer": ans}
            if summary:
                item["process_summary"] = summary
            turns.append(item)
            current_req = None
    return turns


def _evidence_json(
    history: dspy.History | None,
    *,
    max_chars: int = _MAX_EVIDENCE_CHARS,
    current_run_start: int | None = None,
) -> str:
    """Render bounded, user-safe evidence from the loop's tool observations.

    History events appear in two shapes: live in-process events carry
    ``ToolCalls``/``ToolCallResult`` pydantic objects, while histories restored
    from persistence carry plain dicts with the same keys. Only tool names
    and their (already-instrumented, bounded) results are exposed to the
    synthesizer; ``next_thought`` reasoning stays out.

    The result is always parseable JSON: the synthesizer's ``evidence_json``
    input is a document, so an over-budget payload drops whole entries from
    the end rather than slicing the serialized text (see
    ``app.agent.evidence``).
    """
    if history is None:
        return "[]"
    items: list[dict[str, Any]] = []
    messages = getattr(history, "messages", None) or []
    for message_index in range(len(messages) - 1, -1, -1):
        results = _message_tool_results(messages[message_index])
        for result_index in range(len(results) - 1, -1, -1):
            name, value, is_error = results[result_index]
            if name == "submit":
                continue
            items.append(
                {
                    "tool": name,
                    "result": value
                    if isinstance(value, (str, int, float, bool))
                    else json.dumps(value, default=str),
                    "is_error": is_error,
                    **(
                        {
                            "scope": "current_run"
                            if message_index >= current_run_start
                            else "prior_turn",
                            "observation_index": [message_index, result_index],
                        }
                        if current_run_start is not None
                        else {}
                    ),
                }
            )
    full = json.dumps(items, separators=(",", ":"), default=str)
    if len(full) <= max_chars:
        return full
    marker = {
        "tool": "evidence_selection",
        "result": "Older evidence was truncated; newest observations take priority.",
        "is_error": False,
    }
    marker_cost = len(json.dumps(marker, separators=(",", ":"))) + 1
    if max_chars < marker_cost + 4:
        return bounded_json(items, max_chars=max_chars)
    selected = json.loads(bounded_json(items, max_chars=max_chars - marker_cost))
    return json.dumps([*selected, marker], ensure_ascii=False, separators=(",", ":"))


def _message_tool_results(message: Any) -> list[tuple[Any, Any, bool]]:
    """Extract ``(name, value, is_error)`` triples from one history event.

    Accepts both the pydantic event objects a live loop appends and the plain
    dict form a JSON round-trip produces; anything without tool results
    (user turns, evidence breaks) yields nothing.
    """
    if isinstance(message, dict):
        calls = message.get("tool_calls")
    else:
        calls = getattr(message, "tool_calls", None)
    if calls is None:
        return []
    if isinstance(calls, dict):
        container = calls.get("tool_call_results")
    else:
        container = getattr(calls, "tool_call_results", None)
    results: list[tuple[Any, Any, bool]] = []
    for item in _tool_result_entries(container):
        if isinstance(item, dict):
            results.append(
                (item.get("name"), item.get("value"), bool(item.get("is_error", False)))
            )
            continue
        results.append(
            (
                getattr(item, "name", None),
                getattr(item, "value", None),
                bool(getattr(item, "is_error", False)),
            )
        )
    return results


def _tool_result_entries(container: Any) -> list[Any]:
    """Normalize a ``tool_call_results`` carrier to its list of entries.

    The live event stores a ``ToolCallResults`` pydantic model (iterating one
    yields ``("tool_call_results", [...])`` field pairs, not entries), a
    persisted round-trip stores ``{"tool_call_results": [...]}``, and some
    paths already carry the bare list. All three must reach the synthesizer.
    """
    if container is None:
        return []
    if isinstance(container, list):
        return container
    if isinstance(container, dict):
        return _tool_result_entries(container.get("tool_call_results"))
    return _tool_result_entries(getattr(container, "tool_call_results", None))


def _validate_tools(tools: Sequence[dspy.Tool]) -> list[dspy.Tool]:
    validated: list[dspy.Tool] = []
    seen: set[str] = set()
    for tool in tools:
        if not isinstance(tool, dspy.Tool):
            raise TypeError(
                "FleetAgent profiles require explicit dspy.Tool objects; "
                "create them through ToolRegistry or create_dspy_tool()."
            )
        tool = create_dspy_tool(tool)
        name = str(tool.name or "")
        if not name:
            raise ValueError("every tool must have a non-empty name")
        if name in RESERVED_TOOL_NAMES:
            raise ValueError(f"tool name {name!r} is reserved by ReActV2")
        if name in seen:
            raise ValueError(f"duplicate tool: {name}")
        if not str(tool.desc or "").strip():
            raise ValueError(f"tool {name!r} must have a description or docstring")
        if is_async_tool(tool):
            raise TypeError(
                f"tool {name!r} is async, but DSPy 3.4.0 ReActV2 executes "
                "tools synchronously. Use a synchronous adapter or a future "
                "async agent program instead of enabling implicit sync conversion."
            )
        seen.add(name)
        validated.append(tool)
    return validated
