"""Verify frozen live matrix browser evidence against isolated durable state."""

import asyncio
import json
import re
from pathlib import Path

from app.persistence.models import Artifact, Message
from live_acceptance_admin import ROOT, inspect, request, settings
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


async def main():
    b = json.loads((ROOT / "browser-evidence.json").read_text())
    a = json.loads((ROOT / "persisted-audit.json").read_text())
    req = [json.loads(l) for l in (ROOT / "requests.ndjson").read_text().splitlines()]
    per = [
        json.loads(l) for l in (ROOT / "permissions.ndjson").read_text().splitlines()
    ]
    for permission in per:
        assert not (
            (set(permission["exposed"]) & {"write", "edit", "bash"})
            - set(permission["approved"])
        )
    engine = create_async_engine(
        make_url(settings.database_url.get_secret_value()).set(
            database="fleet_acceptance_20261009"
        )
    )
    sessions = async_sessionmaker(engine)
    results = []
    async with sessions() as s:
        for c in b:
            d = next(x for x in a if x["thread_id"] == c["thread_id"])
            runs = d["runs"]
            n = c["case"]
            r = c["repeat"]
            assert c.get("observations")
            boot = request("GET", f"/api/threads/{c['thread_id']}/bootstrap")
            if n == 3:
                assert not runs
            else:
                assert runs and all(
                    x["status"] in ["completed", "cancelled"] for x in runs
                )
                assert (
                    boot["agentState"]
                    and boot["agentState"]["schemaVersion"] == 2
                    and boot["agentState"]["run"]["saveStatus"] == "saved"
                )
                for run in runs:
                    q = next(x for x in req if x.get("run_id") == run["id"])
                    assert (
                        q["model"],
                        q["base_url"],
                        q["response_format"],
                        q["messages_format"],
                        q["provider_key_present"],
                    ) == (
                        "deepseek/deepseek-v4.1-flash",
                        "https://api.commandcode.ai/provider/v1",
                        "json_tool_calls",
                        "system_role",
                        True,
                    )
                    assert all(
                        t["name"] not in ["write", "edit", "bash"]
                        or t["name"] in q["approved_tools"]
                        for t in (run["toolCalls"] or [])
                    )
            answers = [str(x["answer"] or "") for x in runs]
            last = answers[-1] if answers else ""
            facts = {
                1: ["42"],
                2: ["ORBIT-742", "violet"],
                4: ["Aster", "17 November", "420"],
                5: ["Aster", "17 November", "420"],
                6: ["Juniper", "730", "22 December"],
                7: ["Larch", "900"],
                12: ["101"],
            }.get(n, [])
            assert all(f.lower() in last.lower() for f in facts), (r, n, "facts")
            if n in [4, 5]:
                assert runs[-1]["sources"] and any(
                    x["title"] == "acceptance.md" for x in runs[-1]["sources"]
                )
            if n in [5, 6, 7, 12]:
                arts = (
                    await s.scalars(
                        select(Artifact).where(Artifact.thread_id == c["thread_id"])
                    )
                ).all()
                assert len(arts) == 1 and arts[0].status == "ready"
                report = ROOT / "artifacts" / arts[0].storage_key
                if not report.exists():
                    candidates = list(
                        (ROOT / "artifacts").rglob(Path(arts[0].storage_key).name)
                    )
                    assert len(candidates) == 1
                    report = candidates[0]
                text = report.read_text()
                expect = facts if n != 12 else ["STATE_SNAPSHOT", "STATE_DELTA"]
                assert all(f.lower() in text.lower() for f in expect)
                if n == 7:
                    assert "Cedar" not in text and not re.search(r"\b100\b", text)
                if n in [5, 6, 12]:
                    assert Path(c["download"]).read_text() == text
            if n == 6:
                assert all(not x["toolCalls"] for x in runs)
            if n == 7:
                assert "Cedar" not in last and not re.search(r"\b100\b", last)
            if n == 8:
                assert runs[-1]["stateRun"]["evidenceStatus"] == "insufficient"
            if n == 9:
                assert len(runs) == 4
                assert [t["name"] for t in runs[1]["toolCalls"]] == ["write", "read"]
                assert "write" not in [t["name"] for t in runs[2]["toolCalls"]]
                assert (
                    f"APPROVED-{r}"
                    == (ROOT / "workspace" / f"approval-{r}.md").read_text().strip()
                )
                assert "unavailable" in last.lower()
            if n == 10:
                assert runs[0]["status"] == "cancelled"
                peer = await inspect(c["peer"]["thread_id"])
                assert peer[-1]["status"] == "completed"
                assert (
                    f"BETA-{r}" in c["peer"]["text"]
                    and f"ALPHA-{r}" not in c["peer"]["text"]
                )
            if n == 11:
                assert len(c["feedback_lifecycle"]) >= 6
                messages = (
                    await s.scalars(
                        select(Message).where(Message.thread_id == c["thread_id"])
                    )
                ).all()
                assert all(m.feedback_json is None for m in messages)
            if n == 12:
                assert c["historical_search"]["new_run_active"] and all(
                    "Searching" not in t
                    for t in c["historical_search"]["settled_during"]
                )
                assert (
                    c["responsive"]["width"] == 390
                    and c["responsive"]["keyboardInspector"]
                )
            c["result"] = "passed"
            results.append(
                {
                    "repeat": r,
                    "case": n,
                    "thread_id": c["thread_id"],
                    "result": "passed",
                    "runs": [
                        {
                            "id": x["id"],
                            "status": x["status"],
                            "latencySeconds": x["latencySeconds"],
                            "usage": x["usage"],
                        }
                        for x in runs
                    ],
                }
            )
    await engine.dispose()
    (ROOT / "matrix-results.json").write_text(
        json.dumps(
            {
                "revision": json.loads((ROOT / "revision.json").read_text()),
                "passed": len(results),
                "total": 36,
                "cases": results,
            },
            indent=2,
        )
    )
    (ROOT / "browser-evidence.json").write_text(json.dumps(b, indent=2))
    print("36/36 matrix assertions passed")


asyncio.run(main())
