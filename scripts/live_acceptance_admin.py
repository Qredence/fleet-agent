"""Safe REST and database probes for the isolated live-acceptance service."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
from app.persistence.models import Run, RunState
from app.settings import get_settings
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

ROOT = Path(__file__).resolve().parents[1] / ".artifacts/live-acceptance"
settings = get_settings()
headers = {"X-API-Key": settings.api_key.get_secret_value()} if settings.api_key else {}
client = httpx.Client(base_url="http://localhost:8002", headers=headers, timeout=15)


def request(method, path, body=None):
    response = client.request(method, path, json=body)
    response.raise_for_status()
    return response.json() if response.content else None


async def inspect(thread_id):
    url = make_url(settings.database_url.get_secret_value()).set(
        database="fleet_acceptance_20261009"
    )
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine)
    async with sessions() as s:
        runs = (
            await s.scalars(
                select(Run).where(Run.thread_id == thread_id).order_by(Run.reserved_at)
            )
        ).all()
        result = []
        for run in runs:
            states = (
                await s.scalars(select(RunState).where(RunState.run_id == run.id))
            ).all()
            result.append(
                {
                    "id": run.id,
                    "status": run.status,
                    "input_message_id": run.input_message_id,
                    "output_message_id": run.output_message_id,
                    "usage": run.token_usage,
                    "state": states[-1].state_json if states else None,
                }
            )
    await engine.dispose()
    return result


if __name__ == "__main__":
    action = sys.argv[1]
    if action == "setup":
        project = request(
            "POST", "/api/projects", {"name": "Live acceptance 2026-10-09"}
        )
        cases = []
        for repeat in range(1, 4):
            for case in range(1, 13):
                thread = request(
                    "POST",
                    f"/api/projects/{project['id']}/threads",
                    {"title": f"Acceptance {repeat}.{case:02}"},
                )
                cases.append(
                    {
                        "repeat": repeat,
                        "case": case,
                        "project_id": project["id"],
                        "thread_id": thread["id"],
                        "url": f"http://localhost:5173/projects/{project['id']}/threads/{thread['id']}",
                        "result": "pending",
                    }
                )
        (ROOT / "cases.json").write_text(json.dumps(cases, indent=2))
        print(json.dumps({"project_id": project["id"], "scenarios": len(cases)}))
    elif action == "new":
        project_id = json.loads((ROOT / "cases.json").read_text())[0]["project_id"]
        thread = request(
            "POST", f"/api/projects/{project_id}/threads", {"title": sys.argv[2]}
        )
        print(
            json.dumps(
                {
                    "thread_id": thread["id"],
                    "url": f"http://localhost:5173/projects/{project_id}/threads/{thread['id']}",
                }
            )
        )
    elif action == "inspect":
        print(json.dumps(asyncio.run(inspect(sys.argv[2]))))
    elif action == "get":
        print(json.dumps(request("GET", sys.argv[2])))
    elif action == "fault":
        controls = json.loads((ROOT / "controls.json").read_text())
        controls.append(
            {
                "thread_id": sys.argv[2],
                "stage": sys.argv[3],
                "remaining": int(sys.argv[4]),
                **({"run_id": "feedback-only"} if sys.argv[3] == "feedback" else {}),
            }
        )
        (ROOT / "controls.json").write_text(json.dumps(controls))
        print("fault armed for isolated thread")
    elif action == "urls":
        cases = json.loads((ROOT / "cases.json").read_text())
        print(json.dumps([c for c in cases if c["repeat"] == int(sys.argv[2])]))
