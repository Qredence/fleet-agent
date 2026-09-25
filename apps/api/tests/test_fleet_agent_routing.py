import json

import dspy

from app.agent.approval import offered_tool_names
from app.agent.factory import build_tool_profiles
from app.agent.program import FleetAgent
from app.agent.routing import ROUTES, ToolRoute, coerce_route
from app.agent.tool_registry import ToolMetadata, ToolRegistry
from tests.helpers.scripted_lm import ScriptedLM


def _registry() -> ToolRegistry:
    def search(query: str) -> str:
        """Search trusted test evidence."""
        return query

    def artifact(title: str) -> str:
        """Create a test artifact."""
        return title

    def ls(path: str = ".") -> str:
        """List a test workspace."""
        return path

    def write(path: str, content: str) -> str:
        """Write a test workspace file."""
        return f"{path}:{content}"

    def bash(command: str) -> str:
        """Run a test workspace command."""
        return command

    return ToolRegistry(
        [
            (search, ToolMetadata(name="search", capability="retrieval")),
            (
                artifact,
                ToolMetadata(
                    name="artifact",
                    capability="artifact",
                    read_only=False,
                    parallelizable=False,
                ),
            ),
            (ls, ToolMetadata(name="ls", capability="workspace_read")),
            (
                write,
                ToolMetadata(
                    name="write",
                    capability="workspace_write",
                    read_only=False,
                    parallelizable=False,
                ),
            ),
            (
                bash,
                ToolMetadata(
                    name="bash",
                    capability="shell",
                    read_only=False,
                    parallelizable=False,
                ),
            ),
        ]
    )


def test_profiles_are_a_least_privilege_capability_lattice():
    profiles = build_tool_profiles(_registry())

    assert set(profiles) == set(ROUTES)
    assert profiles["direct"] == []
    assert [tool.name for tool in profiles["research"]] == ["search"]
    assert [tool.name for tool in profiles["workspace_read"]] == ["search", "ls"]
    assert [tool.name for tool in profiles["workspace_write"]] == [
        "search",
        "ls",
        "write",
    ]
    assert [tool.name for tool in profiles["workspace_shell"]] == [
        "search",
        "ls",
        "write",
        "bash",
    ]
    assert "write" not in {tool.name for tool in profiles["workspace_read"]}
    assert "bash" not in {tool.name for tool in profiles["workspace_write"]}


def test_routed_program_builds_router_and_react_children_in_init():
    program = FleetAgent(tool_profiles=build_tool_profiles(_registry()), max_iters=3)

    assert isinstance(program.router, dspy.Predict)
    assert all(
        isinstance(program.evidence_agents[route], dspy.ReActV2)
        for route in ROUTES
        if route not in {"direct"}
    )
    # Each route carries exactly its least-privileged tool set.
    assert program.tool_names["direct"] == ()
    assert program.tool_names["workspace_shell"] == ("search", "ls", "write", "bash")
    assert program.predictors()


def test_selected_profile_receives_history_without_rebuilding_modules(monkeypatch):
    program = FleetAgent(tool_profiles=build_tool_profiles(_registry()), max_iters=3)
    history = dspy.History(messages=[{"role": "user", "content": "prior"}])
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        program.router,
        "forward",
        lambda **kwargs: dspy.Prediction(route="workspace_read"),
    )

    def fake_evidence(**kwargs):
        captured.update(kwargs)
        return dspy.Prediction(history=history, termination_reason="evidence_submit")

    monkeypatch.setattr(
        program.evidence_agents["workspace_read"], "forward", fake_evidence
    )
    monkeypatch.setattr(
        program.synthesizer,
        "forward",
        lambda **kwargs: dspy.Prediction(
            answer="done",
            process_summary="inspected",
            key_decisions=[],
            caveats=[],
        ),
    )
    prediction = program(user_request="inspect files", history=history)

    assert prediction.answer == "done"
    assert captured["user_request"] == "inspect files"
    assert captured["history"] is history
    assert prediction.agent_route == "workspace_read"
    # The evidence loop's history rides on the final prediction for
    # continuation; the synthesizer never sees the raw next_thought text.
    assert prediction.history is history


def test_invalid_router_output_falls_back_to_direct_without_escalation(monkeypatch):
    """An out-of-vocabulary router answer must not widen capability."""
    program = FleetAgent(tool_profiles=build_tool_profiles(_registry()), max_iters=3)
    monkeypatch.setattr(
        program.router,
        "forward",
        lambda **kwargs: dspy.Prediction(route="not-a-route"),
    )

    ran: list[str] = []

    def spy(route: ToolRoute):
        def forward(**kwargs):
            del kwargs
            ran.append(route)
            return dspy.Prediction(history=None, termination_reason="evidence_submit")

        return forward

    for route, agent in program.evidence_agents.items():
        monkeypatch.setattr(agent, "forward", spy(route))

    # ``direct`` has no evidence loop: a tool-less profile goes straight to
    # synthesis, so the synthesizer is the only step that can run.
    assert "direct" not in program.evidence_agents
    monkeypatch.setattr(
        program.synthesizer,
        "forward",
        lambda **kwargs: dspy.Prediction(
            answer="direct",
            process_summary="answered directly",
            key_decisions=[],
            caveats=[],
        ),
    )
    prediction = program(user_request="explain pytest", history=None)

    assert prediction.answer == "direct"
    assert prediction.agent_route == "direct"
    assert ran == [], "a degraded route must not run any tool-bearing profile"
    assert coerce_route("not-a-route") == "direct"


def test_json_router_literal_value_error_falls_back_to_direct():
    program = FleetAgent(tool_profiles=build_tool_profiles(_registry()), max_iters=3)
    lm = ScriptedLM([{"content": '{"route": "code"}'}])

    with dspy.context(lm=lm, adapter=dspy.JSONAdapter()):
        assert program._select_route("inspect the code") == "direct"


def test_direct_route_keeps_dict_history_evidence(monkeypatch):
    program = FleetAgent(tool_profiles=build_tool_profiles(_registry()), max_iters=3)
    monkeypatch.setattr(
        program.router,
        "forward",
        lambda **kwargs: dspy.Prediction(route="direct"),
    )
    captured: dict[str, object] = {}

    def fake_synthesis(**kwargs):
        captured.update(kwargs)
        return dspy.Prediction(
            answer="used prior evidence",
            process_summary="",
            key_decisions=[],
            caveats=[],
        )

    monkeypatch.setattr(program.synthesizer, "forward", fake_synthesis)
    history = {
        "messages": [
            {
                "tool_calls": {
                    "tool_call_results": [
                        {"name": "search", "value": "prior fact", "is_error": False}
                    ]
                }
            }
        ]
    }

    prediction = program(user_request="follow up", history=history)

    assert prediction.answer == "used prior evidence"
    assert json.loads(captured["evidence_json"]) == [
        {"tool": "search", "result": "prior fact", "is_error": False}
    ]


def _gated_registry() -> ToolRegistry:
    def search(query: str) -> str:
        """Search trusted test evidence."""
        return query

    def write(path: str, content: str) -> str:
        """Write a test workspace file."""
        return f"{path}:{content}"

    return ToolRegistry(
        [
            (search, ToolMetadata(name="search", capability="retrieval")),
            (
                write,
                ToolMetadata(
                    name="write",
                    capability="workspace_write",
                    read_only=False,
                    parallelizable=False,
                    requires_approval=True,
                ),
            ),
        ]
    )


def test_gated_tools_are_withheld_unless_the_run_approves_them() -> None:
    """The security control that replaced mid-loop approval.

    A tool that requires approval is not merely declined when the run offers no
    approval: it is never placed in the profile, so the model cannot see it or
    be persuaded to call it.
    """
    registry = _gated_registry()

    unapproved = build_tool_profiles(registry, None)
    for route, tools in unapproved.items():
        assert "write" not in {tool.name for tool in tools}, route

    approved = build_tool_profiles(registry, frozenset({"write"}))
    assert "write" in {tool.name for tool in approved["workspace_write"]}
    # approval is scoped to the gated tool; read-only routes still never see it
    assert "write" not in {tool.name for tool in approved["workspace_read"]}


def test_wildcard_approval_offers_every_gated_tool() -> None:
    registry = _gated_registry()
    profiles = build_tool_profiles(registry, frozenset({"*"}))
    assert offered_tool_names(registry.approval_policy(), frozenset({"*"})) == {
        "search",
        "write",
    }
    assert "write" in {tool.name for tool in profiles["workspace_write"]}
