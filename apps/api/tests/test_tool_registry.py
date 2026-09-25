import pytest

from app.agent.tool_registry import (
    ToolMetadata,
    ToolRegistry,
)


def test_registry_preserves_dspy_schema_and_typed_validation():
    def lookup(query: str, limit: int = 2) -> str:
        """Look up bounded values."""
        return f"{query}:{limit}"

    registry = ToolRegistry(
        [(lookup, ToolMetadata(name="lookup", max_output_chars=20))]
    )
    tool = registry.get("lookup").tool

    assert tool.desc == "Look up bounded values."
    assert tool.args["query"]["type"] == "string"
    assert tool.args["limit"]["type"] == "integer"
    assert tool(**{"query": "x", "limit": 3}) == "x:3"
    with pytest.raises(ValueError):
        tool(query=4)
