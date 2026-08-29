"""Typed DSPy tool creation, registration, and bounded execution.

The registry adds execution policy, allowlisting, isolation, and bounded
results around the validated ``dspy.Tool`` objects built by ``tooling.py``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any, Literal, cast

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


class ToolMetadata(BaseModel):
    """Execution policy for one registered tool."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(pattern=TOOL_NAME_PATTERN)
    read_only: bool = True
    idempotent: bool = True
    timeout_seconds: float = Field(default=30.0, gt=0)
    parallelizable: bool = True
    max_output_chars: int = Field(default=2000, gt=0)


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
        """Initialize the registry with the provided tool sources and execution metadata.
        
        Parameters:
        	tools (Iterable[tuple[ToolSource, ToolMetadata]]): Tool sources paired with their execution metadata.
        """
        self._tools: dict[str, RegisteredTool] = {}
        for source, metadata in tools:
            self.register(source, metadata)

    def register(self, source: ToolSource, metadata: ToolMetadata) -> dspy.Tool:
        """
        Create and register a synchronous tool for agent execution.
        
        Parameters:
            source (ToolSource): Tool callable or prebuilt DSPy tool to register.
            metadata (ToolMetadata): Execution policy and catalog metadata for the tool.
        
        Returns:
            dspy.Tool: The registered DSPy tool.
        
        Raises:
            ValueError: If the tool name is already registered or does not match the metadata name.
            TypeError: If the tool is asynchronous.
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
        """
        Retrieve a registered tool by name.
        
        Parameters:
        	name (str): The registered tool name.
        
        Returns:
        	RegisteredTool: The tool and its execution metadata.
        
        Raises:
        	KeyError: If no tool is registered with the specified name.
        """
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

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

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        cancel_token: RunCancelToken | None = None,
    ) -> ToolExecutionResult:
        """
        Execute a registered tool and return a bounded, structured result.
        
        Parameters:
        	name (str): Name of the registered tool to execute.
        	arguments (dict[str, Any]): Keyword arguments passed to the tool.
        	cancel_token (RunCancelToken | None): Optional token used to detect cancellation before execution.
        
        Returns:
        	ToolExecutionResult: Completed, cancelled, or failed execution details with a safe error message when applicable.
        """
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
        """
        Execute a read-only, parallelizable tool with concurrency and timeout limits.
        
        Parameters:
            name (str): Registered name of the tool to execute.
            arguments (dict[str, Any]): Arguments passed to the tool.
        
        Returns:
            ToolExecutionResult: Structured execution outcome, including success, failure,
                timeout, cancellation, or unsupported-tool status.
        """
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
    }
