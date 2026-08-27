"""Static tool catalog shared by the run registry and the public API.

Single source of truth for tool metadata: the engine factory builds its
per-run ``ToolRegistry`` from these entries, and ``GET /api/tools`` exposes
them to the workspace Tools page. Descriptions come from the tools' own
docstrings (first paragraph only — no internal details leave the server).
"""

from __future__ import annotations

from pydantic import BaseModel

from app.agent.tools.docs import SearchDocsTool, get_current_time
from app.agent.tools.report import WriteReportTool
from app.agent.tools.web import FetchPageTool, WebSearchTool
from app.settings import Settings


class ToolCatalogEntry(BaseModel):
    """Public, browser-safe description of one registered tool."""

    name: str
    description: str
    read_only: bool
    idempotent: bool
    parallelizable: bool
    timeout_seconds: int


def _first_paragraph(doc: str | None) -> str:
    """First paragraph of a docstring, whitespace-collapsed."""
    if not doc:
        return ""
    paragraphs = [part.strip() for part in doc.strip().split("\n\n")]
    if not paragraphs:
        return ""
    return " ".join(paragraphs[0].split())


def tool_catalog_entries(settings: Settings) -> list[ToolCatalogEntry]:
    """Catalog for the configured settings.

    Web tools are listed only when a Tavily key is configured, mirroring
    ``_build_web_tools`` so the page never advertises unavailable tools.
    """
    timeout = settings.reasoning_task_timeout_seconds

    def entry(
        name: str,
        doc: str | None,
        *,
        read_only: bool,
        idempotent: bool,
        parallelizable: bool,
    ) -> ToolCatalogEntry:
        return ToolCatalogEntry(
            name=name,
            description=_first_paragraph(doc),
            read_only=read_only,
            idempotent=idempotent,
            parallelizable=parallelizable,
            timeout_seconds=timeout,
        )

    entries: list[ToolCatalogEntry] = []
    if settings.tavily_api_key:
        entries.append(
            entry(
                "web_search",
                WebSearchTool.__call__.__doc__,
                read_only=True,
                idempotent=True,
                parallelizable=True,
            )
        )
        entries.append(
            entry(
                "fetch_page",
                FetchPageTool.__call__.__doc__,
                read_only=True,
                idempotent=True,
                parallelizable=True,
            )
        )
    entries.append(
        entry(
            "search_docs",
            SearchDocsTool.__call__.__doc__,
            read_only=True,
            idempotent=True,
            parallelizable=True,
        )
    )
    entries.append(
        entry(
            "write_report",
            WriteReportTool.__call__.__doc__,
            read_only=False,
            idempotent=True,
            parallelizable=False,
        )
    )
    entries.append(
        entry(
            "get_current_time",
            get_current_time.__doc__,
            read_only=True,
            idempotent=False,
            parallelizable=False,
        )
    )
    return entries


def tool_catalog_by_name(
    settings: Settings,
) -> dict[str, ToolCatalogEntry]:
    """Catalog keyed by tool name for registry construction."""
    return {item.name: item for item in tool_catalog_entries(settings)}
