"""The single tool registry: policy, catalog, and DSPy tool construction.

``TOOL_SPECS`` is the authoritative, model-facing contract for every tool: its
description, its capability tag, and its execution policy. The engine builds
``dspy.Tool`` objects from that table and the prompt text it sends the model is
the table's ``description``; ``GET /api/tools`` renders the same strings. The
browser and the model therefore cannot disagree about what a tool is.

That property is the point. A second catalog used to declare the same tools
separately, and it had already drifted: 6 of the 7 workspace tools showed
different text in the Tools page than the model received.

Only genuinely enforced policy lives here. ``idempotent``, ``timeout_seconds``
and ``max_output_chars`` were dropped because nothing on the live path read
them: ReActV2 is handed raw ``dspy.Tool`` objects, so the registry's own
execution wrapper never ran.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import dspy
from pydantic import BaseModel, ConfigDict, Field

from app.agent.tooling import (
    TOOL_NAME_PATTERN,
    ToolSource,
    create_dspy_tool,
    is_async_tool,
)
from app.settings import Settings

ToolCapability = Literal[
    "retrieval",
    "utility",
    "artifact",
    "workspace_read",
    "workspace_write",
    "shell",
]


class ToolMetadata(BaseModel):
    """One tool's model-facing description and enforced execution policy."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=TOOL_NAME_PATTERN)
    # The text the model receives. Empty falls back to the source's own docstring.
    description: str = ""
    capability: ToolCapability = "utility"
    read_only: bool = True
    parallelizable: bool = True
    # Gated by the approval policy before the tool is called.
    requires_approval: bool = False


class ToolCatalogEntry(BaseModel):
    """Public, browser-safe description of one enabled tool."""

    name: str
    description: str
    capability: ToolCapability
    read_only: bool
    parallelizable: bool
    requires_approval: bool


TOOL_SPECS: Mapping[str, ToolMetadata] = {
    "web_search": ToolMetadata(
        name="web_search",
        description=(
            "Search the web for current information.\n"
            "\n"
            "Returns numbered results, each as an id line, URL line, and "
            "short\n"
            "excerpt. Use fetch_page with one id to read a result in "
            "full."
        ),
        capability="retrieval",
        read_only=True,
        parallelizable=True,
        requires_approval=False,
    ),
    "fetch_page": ToolMetadata(
        name="fetch_page",
        description=(
            "Fetch a current-run web_search result by its id.\n"
            "\n"
            "Result ids from earlier conversation turns are not valid for "
            "this run."
        ),
        capability="retrieval",
        read_only=True,
        parallelizable=True,
        requires_approval=False,
    ),
    "search_docs": ToolMetadata(
        name="search_docs",
        description=(
            "Search the bundled documentation corpus for a short query.\n"
            "\n"
            "Returns up to three brief excerpts (title plus text), best "
            "matches first."
        ),
        capability="retrieval",
        read_only=True,
        parallelizable=True,
        requires_approval=False,
    ),
    "write_report": ToolMetadata(
        name="write_report",
        description=(
            "Write a short markdown report and return it as a downloadable artifact."
        ),
        capability="artifact",
        read_only=False,
        parallelizable=False,
        requires_approval=False,
    ),
    "get_current_time": ToolMetadata(
        name="get_current_time",
        description=("Return the current UTC date and time in ISO 8601 format."),
        capability="utility",
        read_only=True,
        parallelizable=False,
        requires_approval=False,
    ),
    "ls": ToolMetadata(
        name="ls",
        description=("List one workspace directory. Do not use shell for inspection."),
        capability="workspace_read",
        read_only=True,
        parallelizable=True,
        requires_approval=False,
    ),
    "find": ToolMetadata(
        name="find",
        description=("Find workspace paths matching a filename or glob pattern."),
        capability="workspace_read",
        read_only=True,
        parallelizable=True,
        requires_approval=False,
    ),
    "grep": ToolMetadata(
        name="grep",
        description=("Search workspace UTF-8 text files for matching lines."),
        capability="workspace_read",
        read_only=True,
        parallelizable=True,
        requires_approval=False,
    ),
    "read": ToolMetadata(
        name="read",
        description=("Read an exact bounded line range from a known workspace file."),
        capability="workspace_read",
        read_only=True,
        parallelizable=True,
        requires_approval=False,
    ),
    "write": ToolMetadata(
        name="write",
        description=("Create or atomically replace a workspace text file."),
        capability="workspace_write",
        read_only=False,
        parallelizable=False,
        requires_approval=True,
    ),
    "edit": ToolMetadata(
        name="edit",
        description=(
            "Replace exact text in a workspace file; ambiguous matches fail safely."
        ),
        capability="workspace_write",
        read_only=False,
        parallelizable=False,
        requires_approval=True,
    ),
    "bash": ToolMetadata(
        name="bash",
        description=(
            "Run a bounded command with a minimal environment in the workspace."
        ),
        capability="shell",
        read_only=False,
        parallelizable=False,
        requires_approval=True,
    ),
}


def workspace_root(settings: Settings) -> Path:
    """Resolve the one server-configured workspace root, fail-closed in prod."""
    if settings.workspace_root:
        return Path(settings.workspace_root)
    if settings.environment == "development":
        # tool_registry -> agent -> app -> api -> apps -> repository root
        return Path(__file__).resolve().parents[4]
    raise RuntimeError(
        "workspace_root must be explicitly configured outside development"
    )


def workspace_root_available(settings: Settings) -> bool:
    """Return whether the configured workspace can actually be opened."""
    if not settings.workspace_read_tools_enabled:
        return False
    if settings.workspace_root:
        root = Path(settings.workspace_root).expanduser()
    elif settings.environment == "development":
        root = Path(__file__).resolve().parents[4]
    else:
        return False
    return root.resolve().is_dir()


def enabled_tool_names(settings: Settings) -> tuple[str, ...]:
    """The single statement of which tools this deployment enables.

    The engine build and the public Tools page both read it, so a tool cannot be
    listed but unavailable, or available but unlisted.
    """
    names: list[str] = []
    if settings.tavily_api_key:
        names += ["web_search", "fetch_page"]
    names += ["search_docs", "write_report", "get_current_time"]
    if workspace_root_available(settings):
        names += ["ls", "find", "grep", "read"]
        if settings.workspace_write_tools_enabled:
            names += ["write", "edit"]
        if settings.workspace_bash_tool_enabled:
            names += ["bash"]
    return tuple(names)


def tool_catalog(settings: Settings) -> list[ToolCatalogEntry]:
    """Render the enabled tools for the browser from the same table."""
    return [
        ToolCatalogEntry(
            name=name,
            description=TOOL_SPECS[name].description,
            capability=TOOL_SPECS[name].capability,
            read_only=TOOL_SPECS[name].read_only,
            parallelizable=TOOL_SPECS[name].parallelizable,
            requires_approval=TOOL_SPECS[name].requires_approval,
        )
        for name in enabled_tool_names(settings)
    ]


@dataclass(frozen=True)
class RegisteredTool:
    tool: dspy.Tool
    metadata: ToolMetadata


class ToolRegistry:
    """Registry of explicit ``dspy.Tool`` objects and execution policy."""

    def __init__(self, tools: Iterable[tuple[ToolSource, ToolMetadata]] = ()) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        for source, metadata in tools:
            self.register(source, metadata)

    def register(self, source: ToolSource, metadata: ToolMetadata) -> dspy.Tool:
        """Create/register a tool before an agent run starts.

        The registry name, the model-visible schema name, and the public catalog
        name must all agree, so one tool can never be referred to by two names.
        """
        if metadata.name in self._tools:
            raise ValueError(f"duplicate tool: {metadata.name}")

        if isinstance(source, dspy.Tool) and source.name != metadata.name:
            raise ValueError(
                "prebuilt dspy.Tool name does not match metadata: "
                f"{source.name!r} != {metadata.name!r}"
            )

        if isinstance(source, dspy.Tool) and not metadata.description:
            # Nothing to apply, so keep the object the caller built: a caller
            # that already constructed a dspy.Tool keeps a stable identity.
            tool = source
        else:
            tool = create_dspy_tool(
                source,
                name=metadata.name,
                description=metadata.description or None,
            )

        if tool.name != metadata.name:
            raise ValueError(
                "model-visible tool name does not match registry metadata: "
                f"{tool.name!r} != {metadata.name!r}"
            )
        if is_async_tool(tool):
            raise TypeError(
                f"tool {metadata.name!r} is async, but ToolRegistry and the "
                "DSPy 3.3.1 ReActV2 path execute tools synchronously"
            )

        self._tools[metadata.name] = RegisteredTool(tool=tool, metadata=metadata)
        return tool

    def get(self, name: str) -> RegisteredTool:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def approval_policy(self) -> dict[str, ToolMetadata]:
        """Return the immutable approval policy for the registered tools."""
        return {name: registered.metadata for name, registered in self._tools.items()}

    def dspy_tools(
        self,
        *,
        read_only_only: bool = False,
        allowed_names: Iterable[str] | None = None,
    ) -> list[dspy.Tool]:
        """Return the exact tools available to one DSPy program.

        ``allowed_names`` is the safe dynamic-selection mechanism: the server
        decides which trusted tools are available, then ReActV2 decides which of
        those tools to invoke. It never generates executable Python at runtime.
        """
        allowed = set(allowed_names) if allowed_names is not None else None
        unknown = allowed.difference(self._tools) if allowed is not None else set()
        if unknown:
            names = ", ".join(sorted(unknown))
            raise KeyError(f"unknown tool(s): {names}")

        return [
            registered.tool
            for name, registered in self._tools.items()
            if (allowed is None or name in allowed)
            and not (
                read_only_only
                and not (
                    registered.metadata.read_only and registered.metadata.parallelizable
                )
            )
        ]

    def dspy_tools_for_capabilities(
        self, capabilities: set[ToolCapability]
    ) -> list[dspy.Tool]:
        """Return registered tools whose policy grants a capability."""
        return [
            registered.tool
            for registered in self._tools.values()
            if registered.metadata.capability in capabilities
        ]
