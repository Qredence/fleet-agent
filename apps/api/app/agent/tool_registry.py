"""Typed DSPy tool creation, registration, and bounded execution.

The registry adds execution policy, allowlisting, isolation, and bounded
results around the validated ``dspy.Tool`` objects built by ``tooling.py``.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, cast, get_type_hints

import dspy
from pydantic import BaseModel, ConfigDict, Field

from app.agent.instrumented import preview
from app.agent.tooling import (
    TOOL_NAME_PATTERN,
    ToolSource,
    clone_dspy_tool,
    create_dspy_tool,
    is_async_tool,
)
from app.agui.cancel_token import RunCancelledError, RunCancelToken
from app.contracts.domain import ArtifactResult, SourceResult

ToolCapability = Literal[
    "retrieval",
    "utility",
    "artifact",
    "workspace_read",
    "workspace_write",
    "shell",
]


class ToolMetadata(BaseModel):
    """Execution policy for one registered tool."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=TOOL_NAME_PATTERN)
    capability: ToolCapability = "utility"
    read_only: bool = True
    idempotent: bool = True
    timeout_seconds: float = Field(default=30.0, gt=0)
    parallelizable: bool = True
    max_output_chars: int = Field(default=2000, gt=0)
    # Executable by the approval-aware ReAct boundary before the tool is called.
    requires_approval: bool = False


class ToolExecutionResult(BaseModel):
    """Bounded internal result shared by workers and the synthesizer."""

    status: Literal["completed", "failed", "cancelled"]
    model_output: str = ""
    structured_value: Any = None
    sources: list[SourceResult] = Field(default_factory=list)
    artifacts: list[ArtifactResult] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


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

        Existing ``dspy.Tool`` objects must already use the catalog name. This
        prevents the model-visible schema, execution registry, and public tools
        page from silently referring to one tool by different names.
        """
        if metadata.name in self._tools:
            raise ValueError(f"duplicate tool: {metadata.name}")

        if isinstance(source, dspy.Tool):
            if source.name != metadata.name:
                raise ValueError(
                    "prebuilt dspy.Tool name does not match metadata: "
                    f"{source.name!r} != {metadata.name!r}"
                )
            tool = create_dspy_tool(source)
        else:
            tool = create_dspy_tool(source, name=metadata.name)

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
        isolate: bool = False,
    ) -> list[dspy.Tool]:
        """Return the exact tools available to one DSPy program.

        ``allowed_names`` is the safe dynamic-selection mechanism: the server
        decides which trusted tools are available, then ReActV2 decides which of
        those tools to invoke. It never generates executable Python at runtime.

        ``isolate`` creates fresh Tool wrappers and asks stateful callable
        objects that implement ``clone_for_worker`` for per-worker instances.
        Plain functions remain shared because they have no instance state.
        """
        allowed = set(allowed_names) if allowed_names is not None else None
        unknown = allowed.difference(self._tools) if allowed is not None else set()
        if unknown:
            names = ", ".join(sorted(unknown))
            raise KeyError(f"unknown tool(s): {names}")

        result: list[dspy.Tool] = []
        clones: dict[int, Callable[..., Any]] = {}
        for name, registered in self._tools.items():
            if allowed is not None and name not in allowed:
                continue
            if read_only_only and not (
                registered.metadata.read_only and registered.metadata.parallelizable
            ):
                continue
            if not isolate:
                result.append(registered.tool)
                continue

            function = _clone_for_worker(registered.tool.func, clones)
            cloned = clone_dspy_tool(registered.tool, function)
            if is_async_tool(cloned):
                raise TypeError(f"isolated tool {name!r} unexpectedly became async")
            result.append(cloned)
        return result

    def dspy_tools_for_capabilities(
        self, capabilities: set[ToolCapability]
    ) -> list[dspy.Tool]:
        """Return registered tools whose policy grants a capability."""
        return [
            registered.tool
            for registered in self._tools.values()
            if registered.metadata.capability in capabilities
        ]

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        cancel_token: RunCancelToken | None = None,
    ) -> ToolExecutionResult:
        """Execute synchronously and convert all failures to safe results."""
        try:
            registered = self.get(name)
        except KeyError:
            return ToolExecutionResult(
                status="failed",
                error_code="unknown_tool",
                error_message="The requested tool is not available.",
            )

        started = time.monotonic()
        try:
            if cancel_token is not None:
                cancel_token.check()
            value = registered.tool(**arguments)
            sources = list(getattr(registered.tool.func, "last_sources", None) or [])
            artifacts = list(
                getattr(registered.tool.func, "last_artifacts", None) or []
            )
            output = _bounded_output(value, registered.metadata.max_output_chars)
            return ToolExecutionResult(
                status="completed",
                model_output=output,
                structured_value=value,
                sources=sources,
                artifacts=artifacts,
                metadata=_execution_metadata(registered.metadata, started),
            )
        except RunCancelledError:
            return ToolExecutionResult(
                status="cancelled",
                error_code="run_cancelled",
                error_message="The task was cancelled before the tool completed.",
                metadata=_execution_metadata(registered.metadata, started),
            )
        except Exception:
            return ToolExecutionResult(
                status="failed",
                error_code="tool_execution_failed",
                error_message=f"The {registered.metadata.name} tool call failed.",
                metadata=_execution_metadata(registered.metadata, started),
            )


class BoundedReadOnlyExecutor:
    """Run eligible registry tools concurrently with a per-run fan-out cap."""

    def __init__(
        self,
        registry: ToolRegistry,
        *,
        max_parallel: int,
        task_timeout_seconds: float,
        cancel_token: RunCancelToken | None = None,
    ) -> None:
        self._registry = registry
        self._semaphore = asyncio.Semaphore(max_parallel)
        self._task_timeout_seconds = task_timeout_seconds
        self._cancel_token = cancel_token

    async def execute(
        self, name: str, arguments: dict[str, Any]
    ) -> ToolExecutionResult:
        try:
            registered = self._registry.get(name)
        except KeyError:
            return ToolExecutionResult(
                status="failed",
                error_code="unknown_tool",
                error_message="The requested tool is not available.",
            )

        if not registered.metadata.read_only or not registered.metadata.parallelizable:
            return ToolExecutionResult(
                status="failed",
                error_code="tool_not_parallelizable",
                error_message="This tool is reserved for serialized execution.",
            )
        if self._cancel_token is not None and self._cancel_token.cancelled:
            return ToolExecutionResult(
                status="cancelled",
                error_code="run_cancelled",
                error_message="The task was cancelled before the tool started.",
            )

        async with self._semaphore:
            if self._cancel_token is not None and self._cancel_token.cancelled:
                return ToolExecutionResult(
                    status="cancelled",
                    error_code="run_cancelled",
                    error_message="The task was cancelled before the tool started.",
                )
            timeout = min(
                registered.metadata.timeout_seconds, self._task_timeout_seconds
            )
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(
                        self._registry.execute,
                        name,
                        arguments,
                        cancel_token=self._cancel_token,
                    ),
                    timeout=timeout,
                )
            except TimeoutError:
                return ToolExecutionResult(
                    status="failed",
                    error_code="tool_timeout",
                    error_message="The tool call exceeded its time limit.",
                    metadata={"timeoutSeconds": timeout},
                )
            except asyncio.CancelledError:
                if self._cancel_token is not None:
                    self._cancel_token.cancel()
                raise


def _clone_for_worker(
    function: Callable[..., Any], clones: dict[int, Callable[..., Any]]
) -> Callable[..., Any]:
    identity = id(function)
    if identity in clones:
        return clones[identity]

    clone_method = getattr(function, "clone_for_worker", None)
    if clone_method is None:
        clones[identity] = function
        return function

    clone = cast(Callable[..., Any], clone_method(clones))
    if not callable(clone):
        raise TypeError("clone_for_worker must return a callable")
    clones[identity] = clone
    return clone


def wrap_tool_with_guard(tool: dspy.Tool, guard: Callable[[], None]) -> dspy.Tool:
    """Return a clone of ``tool`` whose calls run ``guard`` first.

    DSPy 3.3.1's ``with_callbacks`` swallows exceptions raised inside start
    callbacks, so budget and cancellation hooks cannot abort a call from
    ``BaseCallback`` handlers. Wrapping the callable puts the check on the
    real execution path while preserving the original signature, type hints,
    and JSON schema so DSPy tool inference is unchanged.
    """
    original = tool.func
    hints_target = (
        original
        if inspect.isfunction(original) or inspect.ismethod(original)
        else type(original).__call__
    )

    @functools.wraps(original)
    def guarded(**kwargs: Any) -> Any:
        guard()
        return original(**kwargs)

    # Preserve the real signature and annotations: clone_dspy_tool's
    # validation and DSPy's schema inference must see the original contract.
    guarded.__annotations__ = dict(get_type_hints(hints_target))
    guarded.__signature__ = inspect.signature(hints_target)  # type: ignore[attr-defined]
    return clone_dspy_tool(tool, guarded)


def _bounded_output(value: Any, limit: int) -> str:
    if isinstance(value, str):
        return preview(value)[:limit]
    try:
        return preview(str(value))[:limit]
    except Exception:
        return "The tool returned a value that could not be displayed."


def _execution_metadata(metadata: ToolMetadata, started: float) -> dict[str, Any]:
    return {
        "tool": metadata.name,
        "durationMs": int((time.monotonic() - started) * 1000),
        "readOnly": metadata.read_only,
        "idempotent": metadata.idempotent,
        "capability": metadata.capability,
    }
