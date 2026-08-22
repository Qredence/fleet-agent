"""GET /metrics — in-process counters/gauges/latencies as JSON."""

from fastapi import APIRouter, Request

from app.services.metrics import MetricsRegistry

router = APIRouter(tags=["metrics"])


@router.get("/metrics")
async def metrics(request: Request) -> dict[str, object]:
    registry: MetricsRegistry = request.app.state.metrics
    return registry.snapshot()
