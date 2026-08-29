from __future__ import annotations

import dspy
import pytest
from pydantic import SecretStr

from app.agent.factory import build_dspy_engine
from app.agent.program import FleetAgent
from app.agent.tool_registry import ToolMetadata, ToolRegistry
from app.agent.tooling import create_dspy_tool
from app.settings import Settings


def lookup_docs(query: str) -> str:
    """Look up a short query in the test documentation."""
    return f"found:{query}"


def test_fleet_agent_is_a_first_class_dspy_module() -> None:
    tool = create_dspy_tool(lookup_docs)
    program = FleetAgent(tools=[tool], max_iters=4)

    assert isinstance(program, dspy.Module)
    assert program.tool_names == ("lookup_docs",)
    assert program.get_tool("lookup_docs") is tool
    assert program.react.tools["lookup_docs"] is tool
    assert program.predictors() == [program.react.react]


def test_fleet_agent_requires_explicit_dspy_tools() -> None:
    with pytest.raises(TypeError, match="explicit dspy.Tool"):
        FleetAgent(tools=[lookup_docs], max_iters=2)  # type: ignore[list-item]


def test_fleet_agent_rejects_async_tools_under_sync_react_v2() -> None:
    async def async_lookup(query: str) -> str:
        """Look up a query asynchronously."""
        return query

    tool = create_dspy_tool(async_lookup)
    with pytest.raises(TypeError, match="executes tools synchronously"):
        FleetAgent(tools=[tool], max_iters=2)


def test_tool_registry_creates_real_dspy_tools() -> None:
    metadata = ToolMetadata(name="lookup_docs", timeout_seconds=5)
    registry = ToolRegistry([(lookup_docs, metadata)])

    registered = registry.get("lookup_docs")
    assert isinstance(registered.tool, dspy.Tool)
    assert registered.tool.name == "lookup_docs"
    assert registered.tool.desc.startswith("Look up a short query")
    assert registered.tool.args == {"query": {"type": "string"}}
    assert registry.dspy_tools() == [registered.tool]


def test_tool_registry_accepts_prebuilt_tool_without_rewrapping() -> None:
    tool = create_dspy_tool(
        lookup_docs,
        name="docs",
        description="Search the test documentation by query.",
        arg_descriptions={"query": "The short search query."},
    )
    registry = ToolRegistry([(tool, ToolMetadata(name="docs"))])

    assert registry.get("docs").tool is tool
    assert tool.args["query"]["description"] == "The short search query."


def test_tool_registry_rejects_prebuilt_name_drift() -> None:
    tool = create_dspy_tool(lookup_docs, name="docs")
    with pytest.raises(ValueError, match="does not match metadata"):
        ToolRegistry([(tool, ToolMetadata(name="other"))])


def test_tool_registry_rejects_untyped_arguments() -> None:
    def untyped_lookup(query) -> str:  # type: ignore[no-untyped-def]
        """Look up an untyped query."""
        return str(query)

    with pytest.raises(TypeError, match="untyped argument"):
        create_dspy_tool(untyped_lookup)


def test_tool_registry_rejects_invalid_names_and_variadic_schemas() -> None:
    def variadic(**kwargs: str) -> str:
        """Return variadic values."""
        return str(kwargs)

    with pytest.raises(ValueError, match="tool names"):
        create_dspy_tool(lookup_docs, name="invalid tool")
    with pytest.raises(TypeError, match="unsupported parameter"):
        create_dspy_tool(variadic)


def test_tool_registry_requires_a_typed_return_value() -> None:
    def missing_return(query: str):  # type: ignore[no-untyped-def]
        """Return a value without declaring its type."""
        return query

    with pytest.raises(TypeError, match="return annotation"):
        create_dspy_tool(missing_return)


def test_sync_registry_rejects_async_tools() -> None:
    async def async_lookup(query: str) -> str:
        """Look up a query asynchronously."""
        return query

    tool = create_dspy_tool(async_lookup)
    with pytest.raises(TypeError, match="execute tools synchronously"):
        ToolRegistry([(tool, ToolMetadata(name="async_lookup"))])


def test_tool_allowlist_selects_availability_not_execution() -> None:
    def current_time() -> str:
        """Return a deterministic test time."""
        return "now"

    registry = ToolRegistry(
        [
            (lookup_docs, ToolMetadata(name="lookup_docs")),
            (current_time, ToolMetadata(name="current_time")),
        ]
    )

    selected = registry.dspy_tools(allowed_names=["lookup_docs"])
    assert [tool.name for tool in selected] == ["lookup_docs"]
    with pytest.raises(KeyError, match="unknown tool"):
        registry.dspy_tools(allowed_names=["missing"])


def test_factory_builds_fleet_agent_with_explicit_tools() -> None:
    settings = Settings(
        llm_model="openai/test-model",
        llm_api_key=SecretStr("sk-test"),
        llm_max_iters=3,
    )
    engine = build_dspy_engine(settings)
    program = engine._program_factory()  # type: ignore[attr-defined]

    assert isinstance(program, FleetAgent)
    assert all(isinstance(tool, dspy.Tool) for tool in program.tools)
    assert program.tool_names == ("search_docs", "get_current_time")
