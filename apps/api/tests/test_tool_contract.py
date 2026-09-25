"""The model and the Tools page must read the same tool contract.

A second catalog used to declare the tools separately from the registry, and it
had already drifted: 6 of the 7 workspace tools showed different descriptions in
the browser than the model received. ``TOOL_SPECS`` is now the single source,
and these tests lock the property that makes drift impossible.
"""

from __future__ import annotations

from pathlib import Path

from app.agent.tool_registry import (
    TOOL_SPECS,
    ToolMetadata,
    ToolRegistry,
    enabled_tool_names,
    tool_catalog,
)
from app.agent.tools.workspace import WorkspacePolicy, WorkspaceTools
from app.settings import Settings


def _probe(query: str) -> str:
    """A docstring the table may deliberately override."""
    return query


def test_table_description_wins_over_the_source_docstring() -> None:
    """The table is the model-facing contract, not the docstring."""
    registry = ToolRegistry([(_probe, ToolMetadata(name="probe"))])
    assert "docstring the table may" in str(registry.get("probe").tool.desc)

    registry = ToolRegistry(
        [(_probe, ToolMetadata(name="probe", description="Table text."))]
    )
    assert registry.get("probe").tool.desc == "Table text."


def _workspace_tools(tmp_path: Path) -> list:
    return WorkspaceTools(
        WorkspacePolicy(
            root=tmp_path,
            max_read_bytes=1024,
            max_write_bytes=1024,
            max_output_chars=1024,
            bash_default_timeout_seconds=5,
            bash_max_timeout_seconds=10,
            allow_write=True,
            allow_bash=True,
        )
    ).dspy_tools()


def test_registry_overrides_every_workspace_tool_description(tmp_path: Path) -> None:
    """The registry wins over the description a tool passes for itself.

    This is the mechanism that removes the drift, and it is the part worth
    pinning: ``WorkspaceTools.dspy_tools()`` authors its own ``description=``
    values, and they must not be what the model ends up reading.
    """
    sources = _workspace_tools(tmp_path)
    assert len(sources) == 7

    for tool in sources:
        name = str(tool.name)
        registry = ToolRegistry(
            [(tool, ToolMetadata(name=name, description="Authoritative text."))]
        )
        assert registry.get(name).tool.desc == "Authoritative text.", name
        # and the tool really did carry a different string of its own
        assert str(tool.desc) != "Authoritative text."


def test_shipped_table_matches_the_model_text(tmp_path: Path) -> None:
    """No accidental change: the table's text is what the engine hands the model."""
    sources = _workspace_tools(tmp_path)
    registry = ToolRegistry([(tool, TOOL_SPECS[str(tool.name)]) for tool in sources])
    for tool in sources:
        name = str(tool.name)
        assert registry.get(name).tool.desc == TOOL_SPECS[name].description, name


def test_every_spec_carries_a_model_facing_description() -> None:
    """A policy entry with no text would silently fall back to a docstring."""
    missing = sorted(name for name, spec in TOOL_SPECS.items() if not spec.description)
    assert missing == []


def test_catalog_renders_the_table_not_a_copy(tmp_path: Path) -> None:
    settings = Settings(
        environment="development",
        workspace_root=str(tmp_path),
        workspace_write_tools_enabled=True,
        workspace_bash_tool_enabled=True,
        tavily_api_key="tvly-test-key",
    )
    entries = tool_catalog(settings)
    assert [entry.name for entry in entries] == list(enabled_tool_names(settings))
    for entry in entries:
        assert entry.description == TOOL_SPECS[entry.name].description, entry.name
        assert entry.requires_approval == TOOL_SPECS[entry.name].requires_approval


def test_enabled_names_match_the_registry_the_engine_builds(tmp_path: Path) -> None:
    """The Tools page cannot list a tool the engine will not build, or vice versa."""
    settings = Settings(
        environment="development",
        workspace_root=str(tmp_path),
        workspace_write_tools_enabled=True,
        workspace_bash_tool_enabled=True,
    )
    workspace = WorkspaceTools(
        WorkspacePolicy(
            root=tmp_path,
            max_read_bytes=1024,
            max_write_bytes=1024,
            max_output_chars=1024,
            bash_default_timeout_seconds=5,
            bash_max_timeout_seconds=10,
            allow_write=True,
            allow_bash=True,
        )
    )
    built = {
        *(str(t.name) for t in workspace.dspy_tools()),
        "search_docs",
        "write_report",
        "get_current_time",
    }
    assert built == set(enabled_tool_names(settings))
