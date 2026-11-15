"""Concurrent SSE load harness (plan.md Testing / Load tests).

Runs N simultaneous AG-UI streams against a LOCAL server (fixtures mode —
no provider needed) and reports connection splits:

    uv run python scripts/load_sse.py --connections 20 --requests 2

Prints p50/p95 timings for RUN_STARTED, first STATE_DELTA, first tool event,
and terminal, plus error deltas under saturation (semaphore 429s expected
past max_concurrent_runs in engine mode; fixtures mode is unlimited).
"""

import argparse
import asyncio
import json
import os
import statistics
import time
import uuid
from typing import Any

import httpx

BODY_TEMPLATE: dict[str, Any] = {
    "state": None,
    "tools": [],
    "context": [],
    "forwardedProps": None,
}


async def consume_one(
    client: httpx.AsyncClient,
    index: int,
    *,
    thread_id: str,
    run_batch: str,
) -> dict[str, float | str]:
    body = {
        **BODY_TEMPLATE,
        "threadId": thread_id,
        "runId": f"load-run-{run_batch}-{index}",
        "messages": [
            {
                "id": f"m-{run_batch}-{index}",
                "role": "user",
                "content": "How does state sync work?",
            }
        ],
    }
    marks: dict[str, float | str] = {}
    start = time.perf_counter()
    try:
        async with client.stream("POST", "/api/agent", json=body) as response:
            marks["status"] = response.status_code
            first_delta_at: float | None = None
            first_tool_at: float | None = None
            run_started_at: float | None = None
            async for line in response.aiter_lines():
                now = time.perf_counter()
                if not line.startswith("data: "):
                    continue
                line_delta = now - start
                try:
                    event = json.loads(line.removeprefix("data: "))
                except json.JSONDecodeError:
                    continue
                event_type = event.get("type")
                if event_type == "RUN_STARTED" and run_started_at is None:
                    run_started_at = line_delta
                elif event_type == "STATE_DELTA" and first_delta_at is None:
                    first_delta_at = line_delta
                elif event_type == "TOOL_CALL_START" and first_tool_at is None:
                    first_tool_at = line_delta
                elif event_type in {"RUN_FINISHED", "RUN_ERROR"}:
                    marks["terminal_s"] = line_delta
                    marks["terminal_type"] = event_type
                    break
            marks.setdefault("terminal_s", time.perf_counter() - start)
        marks["run_started_s"] = run_started_at if run_started_at is not None else -1.0
        marks["first_delta_s"] = first_delta_at if first_delta_at is not None else -1.0
        marks["first_tool_s"] = first_tool_at if first_tool_at is not None else -1.0
        return marks
    except Exception as exc:  # network errors etc.
        return {
            "status": f"error:{type(exc).__name__}",
            "terminal_s": time.perf_counter() - start,
        }


def pct(values: list[float], percentile: float) -> float:
    if not values:
        return -1.0
    ordered = sorted(values)
    k = max(
        0, min(len(ordered) - 1, int(round((percentile / 100) * (len(ordered) - 1))))
    )
    return ordered[k]


async def main_async() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:8000")
    parser.add_argument("--connections", type=int, default=10)
    parser.add_argument("--requests", type=int, default=1, help="waves per connection")
    parser.add_argument(
        "--api-key",
        default=os.environ.get("FLEET_AGENT_API_KEY", ""),
        help="API key sent as X-API-Key (defaults to FLEET_AGENT_API_KEY)",
    )
    parser.add_argument(
        "--thread-id",
        default="",
        help="Optional threadId override (defaults to a unique id per run)",
    )
    args = parser.parse_args()

    run_batch = uuid.uuid4().hex[:8]
    thread_id = args.thread_id or f"load-t-{run_batch}"
    headers = {"X-API-Key": args.api_key} if args.api_key else {}

    async with httpx.AsyncClient(
        base_url=args.base, headers=headers, timeout=60.0
    ) as client:
        started = time.perf_counter()
        results = await asyncio.gather(
            *(
                consume_one(
                    client,
                    wave * args.connections + index,
                    thread_id=thread_id,
                    run_batch=run_batch,
                )
                for wave in range(args.requests)
                for index in range(args.connections)
            )
        )
    elapsed = time.perf_counter() - started

    statuses: dict[str, int] = {}
    for result in results:
        key = str(result.get("status", "?"))
        statuses[key] = statuses.get(key, 0) + 1

    def ms(value: float | str) -> str:
        return (
            f"{value * 1000:.0f}ms"
            if isinstance(value, float) and value >= 0
            else "n/a"
        )

    for metric in ("run_started_s", "first_delta_s", "first_tool_s", "terminal_s"):
        values: list[float] = []
        for result in results:
            metric_value = result.get(metric)
            if isinstance(metric_value, float) and metric_value >= 0:
                values.append(metric_value)
        if values:
            print(
                f"{metric:>15}: p50={ms(pct(values, 50))} p95={ms(pct(values, 95))} "
                f"mean={ms(statistics.mean(values))}"
            )
        else:
            print(f"{metric:>15}: no data")
    print(f"total wall: {elapsed:.2f}s · statuses: {statuses}")


if __name__ == "__main__":
    asyncio.run(main_async())
