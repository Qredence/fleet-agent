"""Sources & artifacts: contract flow, dedup, lifecycle, safety, and records."""

import asyncio
from pathlib import Path

import pytest

from app.agent.instrumented import instrument_tool
from app.agent.tools.docs import SearchDocsTool
from app.agent.tools.report import WriteReportTool
from app.agui.event_bus import RunEventBus
from app.agui.trace_reducer import TraceReducer, _normalize_uri
from app.contracts.domain import (
    ArtifactFailed,
    ArtifactStarted,
    SourceDiscovered,
    SourceResult,
    ToolStarted,
)
from app.services.artifact_storage import (
    LocalArtifactStorage,
    PathTraversalError,
    sanitize_artifact_name,
)


def bus() -> RunEventBus:
    return RunEventBus(asyncio.get_running_loop())


async def drain(event_bus: RunEventBus, count: int) -> list:
    return [await event_bus.next() for _ in range(count)]


# -- search sources -----------------------------------------------------------


async def test_search_docs_tool_exposes_discovered_sources():
    tool = SearchDocsTool()
    wrapped = instrument_tool(tool, event_bus := bus())
    assert "AG-UI" in wrapped(query="state deltas")

    events = await drain(event_bus, 2 + len(tool.last_sources))
    discovered = [e for e in events if isinstance(e, SourceDiscovered)]
    assert len(discovered) == len(tool.last_sources) > 0
    for event in discovered:
        assert event.source.id
        assert event.source.excerpt is None or len(event.source.excerpt) <= 300


# -- reducer source dedup ------------------------------------------------------


def test_source_dedup_by_canonical_uri_and_id():
    reducer = TraceReducer(thread_id="t", run_id="r")
    reducer.apply_event(
        ToolStarted(
            tool_call_id="tool_1",
            name="search_docs",
            arguments_json="{}",
            input_preview="{}",
        )
    )
    event = SourceDiscovered(
        tool_call_id="tool_1",
        source=SourceResult(
            id="doc-agui-events",
            title="AG-UI events",
            source_type="web",
            uri="https://docs.ag-ui.com/sdk/python/core/events/",
            excerpt="state deltas",
        ),
    )
    ops1 = reducer.apply_event(event)
    assert any(op["path"] == "/sources/-" for op in ops1)
    assert reducer.state["steps"][1]["sourceIds"] == ["doc-agui-events"]

    # Same URI, different trailing slash + fragment + case → deduped away.
    event2 = SourceDiscovered(
        tool_call_id="tool_1",
        source=SourceResult(
            id="dup",
            title="dup",
            source_type="web",
            uri="https://DOCS.AG-UI.COM/sdk/python/core/events/#x",
        ),
    )
    assert reducer.apply_event(event2) == []
    assert len(reducer.state["sources"]) == 1

    # Different URI without matching id → new source.
    event3 = SourceDiscovered(
        tool_call_id="tool_1",
        source=SourceResult(id="other", title="other", source_type="document"),
    )
    reducer.apply_event(event3)
    assert len(reducer.state["sources"]) == 2


def test_normalize_uri():
    assert _normalize_uri("HTTPS://Docs.AG-UI.COM/sdk/python/core/events/#x") == (
        "https://docs.ag-ui.com/sdk/python/core/events"
    )
    assert _normalize_uri("https://x.test/a/") == "https://x.test/a"


# -- storage safety ------------------------------------------------------------


def test_sanitize_artifact_name_rejects_traversal():
    assert sanitize_artifact_name("Report: Q3?") == "Report-Q3"
    # Traversal input collapses to a safe inert name — never a path.
    assert sanitize_artifact_name("..") == "artifact"
    cleaned = sanitize_artifact_name("../../etc/passwd")
    assert "/" not in cleaned and not cleaned.startswith(".") and ".." not in cleaned


def test_local_storage_confined_to_root(tmp_path: Path):
    storage = LocalArtifactStorage(tmp_path)
    with pytest.raises(PathTraversalError):
        storage.resolve_path("../escape.txt")
    size = storage.save(storage_key="thread_1/artifact_1/a.md", content=b"hello")
    assert size == 5
    assert storage.resolve_path("thread_1/artifact_1/a.md").read_bytes() == b"hello"
    storage.delete_prefix("thread_1/")
    assert not storage.resolve_path("thread_1/artifact_1/a.md").exists()


# -- write_report tool lifecycle ----------------------------------------------


async def test_write_report_full_lifecycle(tmp_path: Path):
    event_bus = bus()
    tool = WriteReportTool(
        storage=LocalArtifactStorage(tmp_path),
        bus=event_bus,
        thread_id="thread_9",
        max_bytes=10_000,
    )
    result = tool(title="Demo Report", content="# hello\n\nworld")
    assert "Demo Report" in result

    started, ready = await drain(event_bus, 2)
    files = tmp_path.rglob("*.md")
    for entry in files:
        assert entry.read_text() == "# hello\n\nworld"


async def test_write_report_truncates_oversize_content(tmp_path: Path):
    event_bus = bus()
    tool = WriteReportTool(
        storage=LocalArtifactStorage(tmp_path),
        bus=event_bus,
        thread_id="thread_9",
        max_bytes=10,
    )
    result = tool(title="big", content="x" * 100)
    assert "truncated" in result

    _, ready = await drain(event_bus, 2)
    assert ready.artifact.size_bytes == 10


async def test_write_report_failure_marks_event(tmp_path: Path):
    event_bus = bus()

    class BrokenStorage(LocalArtifactStorage):
        def save(self, *, storage_key: str, content: bytes) -> int:
            raise OSError("disk gone")

    tool = WriteReportTool(
        storage=BrokenStorage(tmp_path),
        bus=event_bus,
        thread_id="thread_9",
        max_bytes=100,
    )
    with pytest.raises(OSError):
        tool(title="doomed", content="x")

    started, failed = await drain(event_bus, 2)
    assert isinstance(started, ArtifactStarted)
    assert isinstance(failed, ArtifactFailed)
    assert failed.artifact_id == started.artifact.id
