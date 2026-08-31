import dspy

from app.agent.factory import build_tool_profiles
from app.agent.program import FleetAgent
from app.agent.routing import ROUTES, coerce_route
from app.agent.tool_registry import ToolMetadata, ToolRegistry


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
        isinstance(getattr(program, f"{route}_agent"), dspy.ReActV2) for route in ROUTES
    )
    assert program.tool_names == ("search", "artifact", "ls", "write", "bash")
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

    monkeypatch.setattr(program.workspace_read_agent, "forward", fake_evidence)
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
    program = FleetAgent(tool_profiles=build_tool_profiles(_registry()), max_iters=3)
    captured: dict[str, object] = {}
    monkeypatch.setattr(
        program.router,
        "forward",
        lambda **kwargs: dspy.Prediction(route="not-a-route"),
    )

    def fake_evidence(**kwargs):
        captured.update(kwargs)
        return dspy.Prediction(history=None, termination_reason="evidence_submit")

    monkeypatch.setattr(program.direct_agent, "forward", fake_evidence)
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
    assert captured["user_request"] == "explain pytest"
    assert coerce_route("not-a-route") == "direct"
