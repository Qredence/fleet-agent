from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str


@router.get("/health")
async def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(status="ok")


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Readiness: reports database connectivity (migrations applied)."""
    try:
        async with request.app.state.db_engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503, content={"status": "not_ready", "database": "down"}
        )
    return JSONResponse(content={"status": "ready"})
