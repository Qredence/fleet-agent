from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.agent.tool_registry import ToolCatalogEntry, tool_catalog
from app.settings import Settings

router = APIRouter(prefix="/api", tags=["tools"])


class ToolCatalogResponse(BaseModel):
    tools: list[ToolCatalogEntry]


@router.get("/tools", response_model=ToolCatalogResponse)
async def list_tools(request: Request) -> ToolCatalogResponse:
    """Return the browser-safe catalog of the tools this deployment enables.

    The entries come from the same table the engine builds the model's tools
    from, so the Tools page can never describe a tool differently from the text
    the model receives.
    """
    settings: Settings = request.app.state.settings
    return ToolCatalogResponse(tools=tool_catalog(settings))
