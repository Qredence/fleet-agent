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
    """
    Build the catalog of tools available under the configured settings.
    
    Web search tools are included only when a Tavily API key is configured. Each entry includes metadata and uses the configured reasoning task timeout.
    
    Parameters:
    	settings (Settings): Application settings used to determine available tools and their timeout.
    
    Returns:
    	list[ToolCatalogEntry]: The configured tool catalog entries.
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
        """
        Create a catalog entry with the specified tool metadata.
        
        Parameters:
            name (str): Tool name.
            doc (str | None): Tool documentation used to derive the description.
            read_only (bool): Whether the tool only reads data.
            idempotent (bool): Whether repeated calls produce the same result.
            parallelizable (bool): Whether the tool can run in parallel with other tools.
        
        Returns:
            ToolCatalogEntry: The configured tool catalog entry.
        """
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
    """Builds the configured tool catalog keyed by tool name.
    
    Returns:
    	dict[str, ToolCatalogEntry]: A mapping from each tool name to its catalog entry.
    """
    return {item.name: item for item in tool_catalog_entries(settings)}
