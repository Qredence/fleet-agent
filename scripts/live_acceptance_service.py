"""Isolated acceptance ASGI wrapper; never imported by the product application.

Requires FLEET_ACCEPTANCE_ROOT and a database named fleet_acceptance_*.
Faults are armed in controls.json by thread and bound to its next explicit run ID.
Only non-secret request configuration and stage counters are written to evidence.
"""

import asyncio
import json
import os
from pathlib import Path
from threading import Lock

from app.agent.program import FleetAgent
from app.contracts.domain import ArtifactReady
from app.main import create_app
from app.persistence.run_persistence import RunPersistence
from app.services.artifact_storage import LocalArtifactStorage
from app.settings import get_settings
from dspy.utils.exceptions import AdapterParseError
from fastapi import Request
from fastapi.responses import JSONResponse

ROOT = Path(os.environ["FLEET_ACCEPTANCE_ROOT"]).resolve()
assert ROOT.name == "live-acceptance"
assert "/fleet_acceptance_" in get_settings().database_url.get_secret_value()
assert get_settings().agent_mode == "engine"
LOCK = Lock()
EVALUATION_STARTED = False
ORIGINAL_BUILDER = None


def read_controls():
    path = ROOT / "controls.json"
    return json.loads(path.read_text()) if path.exists() else []


def fault(stage, thread_id, run_id=None):
    with LOCK:
        controls = read_controls()
        for control in controls:
            if (
                control["thread_id"] == thread_id
                and control["stage"] == stage
                and control.get("run_id")
                and (run_id is None or control["run_id"] == run_id)
                and control["remaining"] > 0
            ):
                control["remaining"] -= 1
                (ROOT / "controls.json").write_text(json.dumps(controls))
                with (ROOT / "faults.ndjson").open("a") as stream:
                    stream.write(
                        json.dumps(
                            {
                                "stage": stage,
                                "thread_id": thread_id,
                                "run_id": control["run_id"],
                            }
                        )
                        + "\n"
                    )
                return True
    return False


original_completed = RunPersistence.run_completed


async def completed(self, **kwargs):
    if fault("terminal", kwargs["thread_id"], kwargs["run_id"]):
        raise RuntimeError("synthetic acceptance persistence failure")
    return await original_completed(self, **kwargs)


RunPersistence.run_completed = completed

original_event = RunPersistence.record_domain_event


async def record_event(self, event, **kwargs):
    if isinstance(event, ArtifactReady) and fault(
        "artifact_metadata", kwargs["thread_id"], kwargs["run_id"]
    ):
        raise RuntimeError("synthetic acceptance metadata failure")
    return await original_event(self, event, **kwargs)


RunPersistence.record_domain_event = record_event

original_save = LocalArtifactStorage.save


def save(self, *, storage_key, content):
    if fault("artifact_file", storage_key.split("/")[0]):
        raise RuntimeError("synthetic acceptance storage failure")
    return original_save(self, storage_key=storage_key, content=content)


LocalArtifactStorage.save = save

original_synthesize = FleetAgent._synthesize


def diagnostic_synthesize(self, **kwargs):
    try:
        result = original_synthesize(self, **kwargs)
        if fault("trace_private_failure", getattr(self, "_acceptance_thread", None)):
            raise RuntimeError("SECRET_TRACE_MARKER PRIVATE_TRACE_CONTENT")
        return result
    except AdapterParseError as exc:
        parsed = exc.parsed_result
        data = {
            "adapter": exc.adapter_name,
            "expected_fields": list(exc.signature.output_fields),
            "parsed_fields": list(parsed) if isinstance(parsed, dict) else [],
            "response_length": len(exc.lm_response),
            "markers": {
                field: f"[[ ## {field} ## ]]" in exc.lm_response
                for field in exc.signature.output_fields
            },
        }
        with (ROOT / "parse-diagnostics.ndjson").open("a") as stream:
            stream.write(json.dumps(data) + "\n")
        raise


FleetAgent._synthesize = diagnostic_synthesize

app = create_app()


@app.middleware("http")
async def acceptance_probe(request: Request, call_next):
    global EVALUATION_STARTED, ORIGINAL_BUILDER
    if request.url.path == "/api/agent" and request.method == "POST":
        body = await request.json()
        thread_id, run_id = body.get("threadId"), body.get("runId")
        if ORIGINAL_BUILDER is None:
            from app.agent.factory import make_engine_builder
            from app.services.metadata_tracing import get_metadata_callback

            ORIGINAL_BUILDER = app.state.engine_builder

            def scoped_builder(bus, *, thread_id, **kwargs):
                active = any(
                    c["thread_id"] == thread_id and c["stage"] == "iteration_limit"
                    for c in read_controls()
                )
                builder = (
                    make_engine_builder(
                        app.state.settings.model_copy(update={"llm_max_iters": 1}),
                        storage=app.state.artifact_storage,
                        telemetry_callback=get_metadata_callback(),
                    )
                    if active
                    else ORIGINAL_BUILDER
                )
                engine = builder(bus, thread_id=thread_id, **kwargs)
                factory = engine._program_factory
                approved = set(kwargs.get("approved") or [])

                def audited_factory():
                    program = factory()
                    program._acceptance_thread = thread_id
                    exposed = {
                        n for names in program.tool_names.values() for n in names
                    }
                    assert not (exposed & {"write", "edit", "bash"} - approved)
                    with (ROOT / "permissions.ndjson").open("a") as stream:
                        stream.write(
                            json.dumps(
                                {
                                    "thread_id": thread_id,
                                    "approved": sorted(approved),
                                    "exposed": sorted(exposed),
                                }
                            )
                            + "\n"
                        )
                    return program

                engine._program_factory = audited_factory
                return engine

            app.state.engine_builder = scoped_builder
        if (ROOT / "evaluate.flag").exists() and not EVALUATION_STARTED:
            from app.agent.provider import parse_provider_override

            override = parse_provider_override(request.headers)
            if override is not None:
                EVALUATION_STARTED = True
                (ROOT / "evaluate.flag").unlink(missing_ok=True)
                asyncio.create_task(asyncio.to_thread(evaluate_provider, override))
        with LOCK:
            controls = read_controls()
            for control in controls:
                if control["thread_id"] == thread_id and not control.get("run_id"):
                    control["run_id"] = run_id
            (ROOT / "controls.json").write_text(json.dumps(controls))
            with (ROOT / "requests.ndjson").open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "thread_id": thread_id,
                            "run_id": run_id,
                            "model": request.headers.get("x-llm-model"),
                            "base_url": request.headers.get("x-llm-base-url"),
                            "response_format": request.headers.get(
                                "x-llm-response-format"
                            ),
                            "messages_format": request.headers.get(
                                "x-llm-messages-format"
                            ),
                            "provider_key_present": bool(
                                request.headers.get("x-llm-key")
                            ),
                            "approved_tools": (body.get("forwardedProps") or {}).get(
                                "approvedTools", []
                            ),
                        }
                    )
                    + "\n"
                )
    if request.method == "PUT" and request.url.path.endswith("/feedback"):
        thread_id = request.url.path.split("/")[3]
        if fault("feedback", thread_id):
            return JSONResponse(
                {"detail": "Synthetic acceptance feedback failure"}, status_code=503
            )
    return await call_next(request)


def evaluate_provider(override):
    # Credential remains ephemeral; use exactly the browser's authorized provider.
    import dspy
    from app.agent.factory import _build_lm
    from app.agent.gateway import close_lm
    from app.agent.routing import ToolRoutingSignature
    from evals.agent_tool_routing import ROUTING_EXAMPLES
    from evals.product_tasks import PRODUCT_HOLDOUT_EXAMPLES, PRODUCT_ROUTING_EXAMPLES
    from evals.scoring import score_router

    lm = _build_lm(app.state.settings, override)
    report = {"model": override.model, "provider": "Command", "promotion": False}
    try:
        for label, examples in [
            ("routing", ROUTING_EXAMPLES),
            (
                "product_regression",
                [*PRODUCT_ROUTING_EXAMPLES, *PRODUCT_HOLDOUT_EXAMPLES],
            ),
        ]:
            expected = {
                (
                    str(e.user_request),
                    str(getattr(e, "conversation_context", "")),
                ): getattr(e, "expected_output_intent", None)
                for e in examples
            }

            class IntentAudit(dspy.Module):
                def __init__(self, expectations):
                    super().__init__()
                    self.predictor = dspy.Predict(ToolRoutingSignature)
                    self.intent_matches = []
                    self.expected = expectations

                def forward(self, **kwargs):
                    prediction = self.predictor(**kwargs)
                    target = self.expected.get(
                        (
                            str(kwargs.get("user_request", "")),
                            str(kwargs.get("conversation_context", "")),
                        )
                    )
                    if target is not None:
                        self.intent_matches.append(
                            getattr(prediction, "output_intent", None) == target
                        )
                    return prediction

            audited = IntentAudit(expected)
            score = score_router(audited, lm, examples)
            report[label] = {
                "cases": len(examples),
                "metrics": score.metrics,
                "mean": score.mean,
                "provider_failures": score.failures,
                "mean_latency_s": score.mean_latency_s,
                "output_intent_cases": len(audited.intent_matches),
                "output_intent_accuracy": sum(audited.intent_matches)
                / len(audited.intent_matches)
                if audited.intent_matches
                else None,
            }
    except Exception as error:  # noqa: BLE001 -- offline attempt retains safe failure type
        report["failure_type"] = type(error).__name__
    finally:
        close_lm(lm)
        (ROOT / "command-routing-results.json").write_text(json.dumps(report, indent=2))
