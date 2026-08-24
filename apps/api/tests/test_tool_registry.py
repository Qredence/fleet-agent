import asyncio
import threading
import time

import pytest

from app.agent.tool_registry import (
    BoundedReadOnlyExecutor,
    ToolMetadata,
    ToolRegistry,
)
from app.agent.tools.docs import SearchDocsTool
from app.agui.cancel_token import RunCancelToken


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


def test_registry_returns_bounded_structured_results_and_sources():
    tool = SearchDocsTool()
    registry = ToolRegistry(
        [(tool, ToolMetadata(name="search_docs", max_output_chars=40))]
    )

    result = registry.execute("search_docs", {"query": "AG-UI"})

    assert result.status == "completed"
    assert len(result.model_output) <= 40
    assert result.structured_value
    assert result.sources
    assert result.error_code is None


def test_registry_converts_failures_and_cancellation_to_safe_results():
    def fail(value: str) -> str:
        raise RuntimeError(f"secret {value}")

    registry = ToolRegistry([(fail, ToolMetadata(name="fail"))])
    failed = registry.execute("fail", {"value": "hidden"})
    assert failed.status == "failed"
    assert failed.error_code == "tool_execution_failed"
    assert failed.error_message == "The fail tool call failed."
    assert "hidden" not in failed.model_dump_json()

    token = RunCancelToken()
    token.cancel()
    cancelled = registry.execute("fail", {"value": "hidden"}, cancel_token=token)
    assert cancelled.status == "cancelled"
    assert cancelled.error_code == "run_cancelled"


@pytest.mark.asyncio
async def test_executor_overlaps_read_only_tasks_and_rejects_side_effects():
    barrier = threading.Barrier(2)

    def read(label: str) -> str:
        barrier.wait(timeout=2)
        return label

    side_effect_called = False

    def write(label: str) -> str:
        nonlocal side_effect_called
        side_effect_called = True
        return label

    registry = ToolRegistry(
        [
            (read, ToolMetadata(name="read", parallelizable=True)),
            (
                write,
                ToolMetadata(
                    name="write",
                    read_only=False,
                    idempotent=False,
                    parallelizable=False,
                ),
            ),
        ]
    )
    executor = BoundedReadOnlyExecutor(registry, max_parallel=2, task_timeout_seconds=2)

    started = time.monotonic()
    first, second = await asyncio.gather(
        executor.execute("read", {"label": "a"}),
        executor.execute("read", {"label": "b"}),
    )
    elapsed = time.monotonic() - started

    assert first.status == second.status == "completed"
    assert elapsed < 1.5
    rejected = await executor.execute("write", {"label": "x"})
    assert rejected.error_code == "tool_not_parallelizable"
    assert not side_effect_called


@pytest.mark.asyncio
async def test_executor_does_not_start_after_cancellation():
    called = False

    def read() -> str:
        nonlocal called
        called = True
        return "unexpected"

    token = RunCancelToken()
    token.cancel()
    registry = ToolRegistry([(read, ToolMetadata(name="read"))])
    executor = BoundedReadOnlyExecutor(
        registry, max_parallel=1, task_timeout_seconds=1, cancel_token=token
    )

    result = await executor.execute("read", {})

    assert result.status == "cancelled"
    assert not called
