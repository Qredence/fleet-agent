from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agent.tools_catalog import ToolCatalogEntry, tool_catalog_entries
from app.settings import Settings

router = APIRouter(prefix="/api", tags=["tools"])


class ToolCatalogResponse(BaseModel):
    tools: list[ToolCatalogEntry]


@router.get("/tools", response_model=ToolCatalogResponse)
async def list_tools(request: Request) -> ToolCatalogResponse:
    """Browser-safe catalog of the tools registered with the DSPy engine."""
    settings: Settings = request.app.state.settings
    return ToolCatalogResponse(tools=tool_catalog_entries(settings))
