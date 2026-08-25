"""Typed, bounded tool execution primitives used by staged DSPy runs.

The registry is deliberately an internal layer.  DSPy still receives normal
``dspy.Tool`` instances, while orchestration gets metadata and a small,
model-safe result envelope.
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
from app.agui.cancel_token import RunCancelledError, RunCancelToken
from app.contracts.domain import ArtifactResult, SourceResult


class ToolMetadata(BaseModel):
    """Execution policy for one registered tool."""

    model_config = ConfigDict(frozen=True)

    name: str
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
    """Registry that adapts existing synchronous callables to ``dspy.Tool``."""

    def __init__(
        self, tools: Iterable[tuple[Callable[..., Any], ToolMetadata]]
    ) -> None:
        self._tools: dict[str, RegisteredTool] = {}
        for function, metadata in tools:
            if metadata.name in self._tools:
                raise ValueError(f"duplicate tool: {metadata.name}")
            tool = dspy.Tool(function, name=metadata.name)
            self._tools[metadata.name] = RegisteredTool(tool=tool, metadata=metadata)

    def get(self, name: str) -> RegisteredTool:
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
        """Return tools for a DSPy invocation.

        ``isolate`` creates fresh ``dspy.Tool`` wrappers and asks stateful
        callable objects that support ``clone_for_worker`` for a per-worker
        instance. Plain functions remain shared because they have no mutable
        instance state.
        """
        allowed = set(allowed_names) if allowed_names is not None else None
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
            result.append(dspy.Tool(function, name=name))
        return result

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
