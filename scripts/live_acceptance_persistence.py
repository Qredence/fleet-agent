"""Audit and seed only the disposable live-acceptance database."""

import asyncio
import copy
import json
import sys
from pathlib import Path

from app.agent.engine import AgentRunResult
from app.persistence.models import DspyHistory, Message, Run, RunState
from app.persistence.run_persistence import RunPersistence
from app.settings import get_settings
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

root = Path(__file__).resolve().parents[1] / ".artifacts/live-acceptance"


async def main():
    settings = get_settings()
    engine = create_async_engine(
        make_url(settings.database_url.get_secret_value()).set(
            database="fleet_acceptance_20261009"
        )
    )
    sessions = async_sessionmaker(engine)
    action = sys.argv[1]
    async with sessions() as s:
        if action == "legacy":
            fs = json.loads((root / "failure-cases.json").read_text())
            async with s.begin():
                for name in ["legacy_confirmed", "legacy_unknown"]:
                    tid = next(f["thread_id"] for f in fs if f["name"] == name)
                    run = await s.scalar(select(Run).where(Run.thread_id == tid))
                    assert run.status == "completed"
                    states = (
                        await s.scalars(
                            select(RunState).where(RunState.run_id == run.id)
                        )
                    ).all()
                    for st in states:
                        data = copy.deepcopy(st.state_json)
                        data["schemaVersion"] = 1
                        data["run"].pop("saveStatus", None)
                        st.state_json = data
                    if name == "legacy_unknown":
                        run.output_message_id = None
                        run.status = "running"
                        run.finished_at = None
                        await s.execute(
                            delete(DspyHistory).where(DspyHistory.thread_id == tid)
                        )
            print("seeded isolated legacy snapshots")
        elif action == "audit":
            cases = json.loads((root / "browser-evidence.json").read_text())
            result = []
            for c in cases:
                runs = (
                    await s.scalars(
                        select(Run)
                        .where(Run.thread_id == c["thread_id"])
                        .order_by(Run.reserved_at)
                    )
                ).all()
                rr = []
                for r in runs:
                    st = await s.scalar(
                        select(RunState)
                        .where(RunState.run_id == r.id)
                        .order_by(RunState.updated_at.desc())
                    )
                    msg = (
                        await s.scalar(
                            select(Message).where(
                                Message.thread_id == c["thread_id"],
                                Message.message_id == r.output_message_id,
                            )
                        )
                        if r.output_message_id
                        else None
                    )
                    d = st.state_json if st else {}
                    rr.append(
                        {
                            "id": r.id,
                            "status": r.status,
                            "terminationReason": r.termination_reason,
                            "answer": msg.message_json.get("content") if msg else None,
                            "stateRun": d.get("run"),
                            "evidence": d.get("evidence"),
                            "toolCalls": d.get("toolCalls"),
                            "artifacts": d.get("artifacts"),
                            "sources": d.get("sources"),
                            "usage": r.token_usage,
                            "latencySeconds": (
                                r.finished_at - r.started_at
                            ).total_seconds()
                            if r.finished_at and r.started_at
                            else None,
                        }
                    )
                result.append(
                    {
                        "repeat": c["repeat"],
                        "case": c["case"],
                        "thread_id": c["thread_id"],
                        "runs": rr,
                        "browserObservations": len(c.get("observations", [])),
                    }
                )
            (root / "persisted-audit.json").write_text(json.dumps(result, indent=2))
            print(
                json.dumps(
                    [
                        {
                            "repeat": c["repeat"],
                            "case": c["case"],
                            "runs": len(c["runs"]),
                            "statuses": [r["status"] for r in c["runs"]],
                            "observations": c["browserObservations"],
                        }
                        for c in result
                    ]
                )
            )
        elif action == "duplicate":
            tid = next(
                case["thread_id"]
                for case in json.loads((root / "failure-cases.json").read_text())
                if case["name"] == "terminal_retry"
            )
            r = await s.scalar(select(Run).where(Run.thread_id == tid))
            st = await s.scalar(select(RunState).where(RunState.run_id == r.id))
            rid = r.id
            mid = r.output_message_id
            state = st.state_json
            before = await s.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.thread_id == tid)
            )
            ok = await RunPersistence(sessions).run_completed(
                thread_id=tid,
                run_id=rid,
                result=AgentRunResult(
                    status="completed", answer="TAMPERED", process_summary=None
                ),
                state_json=state,
                assistant_message_id=mid,
            )
            after = await s.scalar(
                select(func.count())
                .select_from(Message)
                .where(Message.thread_id == tid)
            )
            msg = await s.scalar(
                select(Message).where(
                    Message.thread_id == tid, Message.message_id == mid
                )
            )
            assert ok and before == after and msg.message_json["content"] == "42"
            print("duplicate settlement idempotent; answer unchanged")
    await engine.dispose()


asyncio.run(main())
