"""Structural approval-gating tests for the routed capability lattice.

These pin the security contract without any LM: which tools exist on each
route, that every workspace mutator is approval-gated, that read-only routes
never contain a gated tool, and that untrusted router output degrades to the
least-privileged profile.
"""

from __future__ import annotations

from pathlib import Path

from app.agent.factory import build_tool_profiles
from app.agent.routing import coerce_route
from app.agent.tool_registry import (
    TOOL_SPECS,
    ToolMetadata,
    ToolRegistry,
    enabled_tool_names,
    tool_catalog,
)
from app.settings import Settings

_GATED_TOOLS = {"write", "edit", "bash"}
# write_report creates a managed, bounded artifact inside server-owned
# storage; it is the only intentional ungated mutator.
_UNGATED_MUTATORS = {"write_report"}


def _full_settings(workspace_root: Path) -> Settings:
    return Settings(
        environment="development",
        workspace_root=str(workspace_root),
        workspace_read_tools_enabled=True,
        workspace_write_tools_enabled=True,
        workspace_bash_tool_enabled=True,
        tavily_api_key="tvly-test-key",
    )


def _named_noop(name: str) -> object:
    """A source stand-in whose identity matches the catalog entry name."""

    def tool(query: str) -> str:
        """Test stand-in carrying the production tool's metadata."""
        return query

    tool.__name__ = name  # type: ignore[attr-defined]
    tool.__qualname__ = name  # type: ignore[attr-defined]
    return tool


def _production_registry(workspace_root: Path) -> ToolRegistry:
    """A registry carrying the production table's metadata (no live sources).

    The policy under test is the real one: ``TOOL_SPECS`` is what the engine
    builds the model's tools from, so this exercises the shipping table rather
    than a copy of it.
    """
    settings = _full_settings(workspace_root)
    registrations: list[tuple[object, ToolMetadata]] = [
        (_named_noop(name), TOOL_SPECS[name]) for name in enabled_tool_names(settings)
    ]
    return ToolRegistry(registrations)


def test_every_workspace_mutator_is_approval_gated(tmp_path: Path) -> None:
    entries = tool_catalog(_full_settings(tmp_path))
    by_name = {entry.name: entry for entry in entries}

    assert _GATED_TOOLS <= set(by_name), "gated workspace tools must be present"
    for name in _GATED_TOOLS:
        assert by_name[name].requires_approval is True, name
        assert by_name[name].read_only is False, name
    for entry in entries:
        if entry.name not in _GATED_TOOLS:
            assert entry.requires_approval is False, entry.name


def test_write_report_is_the_only_ungated_mutator(tmp_path: Path) -> None:
    entries = tool_catalog(_full_settings(tmp_path))
    ungated_mutators = {
        entry.name for entry in entries if not entry.read_only
    } - _GATED_TOOLS

    assert ungated_mutators == _UNGATED_MUTATORS


def test_registry_approval_policy_gates_exactly_the_workspace_mutators(
    tmp_path: Path,
) -> None:
    registry = _production_registry(tmp_path)
    policy = registry.approval_policy()

    gated = {name for name, meta in policy.items() if meta.requires_approval}
    assert gated == _GATED_TOOLS


def test_read_only_routes_cannot_reach_gated_tools(tmp_path: Path) -> None:
    profiles = build_tool_profiles(_production_registry(tmp_path))
    policy = _production_registry(tmp_path).approval_policy()

    for route, tools in profiles.items():
        for tool in tools:
            gated = (
                policy.get(tool.name) is not None
                and policy[tool.name].requires_approval
            )
            if route in {"workspace_write", "workspace_shell"}:
                continue
            assert not gated, f"route {route} must not expose gated tool {tool.name}"


def test_mutating_routes_inherit_every_lesser_capability(tmp_path: Path) -> None:
    """The lattice, stated for a run that authorized the gated tools."""
    registry = _production_registry(tmp_path)
    profiles = build_tool_profiles(registry, frozenset({"*"}))
    names = {route: {tool.name for tool in tools} for route, tools in profiles.items()}

    assert names["direct"] == set()
    assert names["research"] < names["workspace_read"] or names["research"] == names[
        "workspace_read"
    ] - {"ls", "find", "grep", "read"}
    assert names["workspace_read"] < names["workspace_write"]
    assert names["workspace_write"] < names["workspace_shell"]
    assert {"write", "edit"} <= names["workspace_write"]
    assert "bash" in names["workspace_shell"]


def test_without_approval_the_mutating_routes_gain_nothing(tmp_path: Path) -> None:
    """A run that authorizes nothing must not be able to reach a gated tool.

    This is the replacement for mid-loop approval: the mutating routes keep
    their read-only tools and gain no capability at all.
    """
    registry = _production_registry(tmp_path)
    unapproved = build_tool_profiles(registry, None)
    unapproved_names = {
        route: {tool.name for tool in tools} for route, tools in unapproved.items()
    }
    gated = {
        name
        for name, meta in registry.approval_policy().items()
        if meta.requires_approval
    }
    assert gated, "the fixture must contain gated tools"

    for route, names in unapproved_names.items():
        assert not (names & gated), f"route {route} reached a gated tool"
    assert unapproved_names["workspace_write"] == unapproved_names["workspace_read"]
    assert unapproved_names["workspace_shell"] == unapproved_names["workspace_read"]


def test_untrusted_router_output_degrades_to_direct() -> None:
    assert coerce_route("workspace_shell") == "workspace_shell"
    assert coerce_route("sudo") == "direct"
    assert coerce_route(None) == "direct"
    assert coerce_route(42) == "direct"
    assert coerce_route("") == "direct"


def test_coerce_route_normalizes_surface_noise_without_elevating() -> None:
    """Whitespace/case/hyphen/quotes recover; invented names stay direct."""
    assert coerce_route("  research  ") == "research"
    assert coerce_route("\nworkspace_read\n") == "workspace_read"
    assert coerce_route("WORKSPACE_WRITE") == "workspace_write"
    assert coerce_route("Workspace_Shell") == "workspace_shell"
    assert coerce_route("workspace-read") == "workspace_read"
    assert coerce_route("workspace write") == "workspace_write"
    assert coerce_route('"artifact"') == "artifact"
    assert coerce_route("'direct'") == "direct"
    assert coerce_route("`research`") == "research"
    # Invented / tool-ish names must not elevate privilege.
    assert coerce_route("web_search") == "direct"
    assert coerce_route("code") == "direct"
    assert coerce_route("bash") == "direct"
    assert coerce_route("read") == "direct"
    assert coerce_route("write") == "direct"
    assert coerce_route("   ") == "direct"
