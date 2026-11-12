"""Unsupported input probes and historical image seed, isolated database only."""

import asyncio
import base64
import json
import uuid

from app.persistence.models import Message, Thread
from live_acceptance_admin import ROOT, client, inspect, settings
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def main():
    url = make_url(settings.database_url.get_secret_value()).set(
        database="fleet_acceptance_20261009"
    )
    assert url.database.startswith("fleet_acceptance_")
    engine = create_async_engine(url)
    sessions = async_sessionmaker(engine)
    results = []
    image = (
        "data:image/png;base64,"
        + base64.b64encode((ROOT / "workspace/test.png").read_bytes()).decode()
    )
    for case in json.loads((ROOT / "cases.json").read_text()):
        if case["case"] != 3:
            continue
        thread = case["thread_id"]
        checks = []
        for mixed in (False, True):
            parts = ([{"type": "text", "text": "safe text"}] if mixed else []) + [
                {"type": "binary", "mimeType": "image/png", "data": "AA=="}
            ]
            body = {
                "threadId": thread,
                "runId": str(uuid.uuid4()),
                "state": None,
                "messages": [{"id": "unsupported", "role": "user", "content": parts}],
                "tools": [],
                "context": [],
                "forwardedProps": None,
            }
            response = client.post("/api/agent", json=body)
            assert response.status_code == 422, (response.status_code, response.text)
            assert response.json()["detail"]["code"] == "unsupported_input_type"
            checks.append(
                {"mixed": mixed, "http_status": 422, "code": "unsupported_input_type"}
            )
        assert not await inspect(thread)
        message_id = "legacy-image-" + thread
        async with sessions() as session:
            session.add(
                Message(
                    id=str(uuid.uuid4()),
                    thread_id=thread,
                    role="user",
                    message_id=message_id,
                    parent_message_id=None,
                    format="aui/v0",
                    message_json={
                        "id": message_id,
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "image": image,
                                "filename": "historical.png",
                            }
                        ],
                        "attachments": [],
                        "metadata": {"custom": {}},
                    },
                )
            )
            row = await session.get(Thread, thread)
            row.active_head_message_id = message_id
            await session.commit()
        results.append(
            {
                "thread_id": thread,
                "repeat": case["repeat"],
                "checks": checks,
                "reserved_runs": 0,
                "historical_image_seeded": True,
            }
        )
    await engine.dispose()
    (ROOT / "input-probes.json").write_text(json.dumps(results, indent=2))
    print(
        json.dumps(
            {
                "unsupported_probes": len(results) * 2,
                "reserved_runs": 0,
                "legacy_seeds": len(results),
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
