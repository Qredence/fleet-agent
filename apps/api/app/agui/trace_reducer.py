"""TraceReducer: agent-run state machine producing AgentWorkspaceState patches.

Deterministic public steps for the MVP:

    step-understand   Understanding the request   (engine starts)
    step-research     Researching with tools      (first ToolStarted)
    step-synthesis    Preparing the response      (engine returns)

Enriched at completion with the model-written process_summary, key_decisions,
and caveats. Never contains raw reasoning — only curated public fields.
"""

import time
from datetime import UTC, datetime
from typing import Any

from app.agent.engine import AgentRunResult
from app.agent.instrumented import preview
from app.contracts.domain import (
    ArtifactFailed,
    ArtifactReady,
    ArtifactStarted,
    SourceDiscovered,
    StepCompleted,
    StepFailed,
    StepStarted,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)
from app.services.source_identity import canonical_source_key

JsonPatchOp = dict[str, Any]


def _normalize_uri(uri: str) -> str:
    """Backward-compatible alias for the shared canonical URI helper."""

    return canonical_source_key({"id": "", "uri": uri})


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class TraceReducer:
    def __init__(
        self,
        *,
        thread_id: str,
        run_id: str,
        prior_state: dict[str, Any] | None = None,
        run_scoped_decisions: bool = False,
    ) -> None:
        self.thread_id = thread_id
        self.run_id = run_id
        self._run_scoped_decisions = run_scoped_decisions
        self._monotonic_start = time.monotonic()
        base: dict[str, Any] = {
            "schemaVersion": 1,
            "threadId": thread_id,
            "run": {
                "id": run_id,
                "status": "running",
                "startedAt": _utc_now(),
                "toolCallCount": 0,
            },
            "steps": [
                {
                    "id": "step-understand",
                    "phase": "understanding",
                    "title": "Understanding the request",
                    "status": "pending",
                    "toolCallIds": [],
                    "sourceIds": [],
                    "artifactIds": [],
                }
            ],
            "decisions": [],
            "toolCalls": [],
            "sources": [],
            "artifacts": [],
            "metrics": {"toolCallCount": 0},
        }
        # Continuation runs inherit only branch-cumulative evidence. Run-local
        # steps, tools, metrics, and caveats are intentionally fresh.
        if prior_state:
            base["sources"] = _unique_by_id(prior_state.get("sources") or [])
            base["artifacts"] = _unique_by_id(prior_state.get("artifacts") or [])
            base["decisions"] = [
                decision
                for decision in _unique_by_id(prior_state.get("decisions") or [])
                if decision.get("status") in (None, "accepted")
            ]
        self.state: dict[str, Any] = base
        self._tool_index: dict[str, int] = {
            str(tool.get("id")): index
            for index, tool in enumerate(self.state["toolCalls"])
            if tool.get("id")
        }
        self._source_index: dict[str, int] = {}
        for index, source in enumerate(self.state["sources"]):
            key = canonical_source_key(
                {
                    "id": source.get("id", ""),
                    "uri": source.get("uri"),
                }
            )
            self._source_index.setdefault(key, index)
        self._artifact_index: dict[str, int] = {
            str(artifact.get("id")): index
            for index, artifact in enumerate(self.state["artifacts"])
            if artifact.get("id")
        }
        self._step_index: dict[str, int] = {
            s["id"]: i for i, s in enumerate(self.state["steps"])
        }
        self._step_started_monotonic: dict[str, float] = {}
        self._tool_started_monotonic: dict[str, float] = {}

    # -- lifecycle ---------------------------------------------------------

    def begin(self) -> list[JsonPatchOp]:
        """RUN_STARTED + snapshot are emitted by the coordinator; this is the
        first delta: understanding starts."""
        return self._start_step("step-understand")

    def complete_understanding(self) -> list[JsonPatchOp]:
        return self._complete_step("step-understand")

    # -- domain events ---------------------------------------------------------

    def apply_event(
        self,
        event: ToolStarted
        | ToolCompleted
        | ToolFailed
        | SourceDiscovered
        | StepStarted
        | StepCompleted
        | StepFailed
        | ArtifactStarted
        | ArtifactReady
        | ArtifactFailed,
    ) -> list[JsonPatchOp]:
        if isinstance(event, ToolStarted):
            return self._tool_started(event)
        if isinstance(event, StepStarted):
            return self._step_started_event(event)
        if isinstance(event, StepCompleted):
            return self._step_completed_event(event)
        if isinstance(event, StepFailed):
            return self._step_failed_event(event)
        if isinstance(event, (ToolCompleted, ToolFailed)):
            return self._tool_settled(event)
        if isinstance(event, SourceDiscovered):
            return self._source_discovered(event)
        if isinstance(event, ArtifactStarted):
            return self._artifact_started(event)
        if isinstance(event, ArtifactReady):
            return self._artifact_ready(event)
        return self._artifact_failed(event)

    def apply_tool_event(
        self, event: ToolStarted | ToolCompleted | ToolFailed
    ) -> list[JsonPatchOp]:
        return self.apply_event(event)

    def _tool_settled(self, event: ToolCompleted | ToolFailed) -> list[JsonPatchOp]:
        idx = self._tool_index.get(event.tool_call_id)
        if idx is None:
            return []
        tool = self.state["toolCalls"][idx]
        ops: list[JsonPatchOp] = []
        tool["status"] = "completed" if isinstance(event, ToolCompleted) else "failed"
        tool["finishedAt"] = _utc_now()
        tool["durationMs"] = event.duration_ms
        if isinstance(event, ToolCompleted):
            tool["outputPreview"] = preview(event.output_preview)
        else:
            tool["errorMessage"] = event.error_message
        for key in (
            "status",
            "finishedAt",
            "durationMs",
            "outputPreview",
            "errorMessage",
        ):
            if key in tool:
                ops.append(
                    {"op": "add", "path": f"/toolCalls/{idx}/{key}", "value": tool[key]}
                )
        return ops

    def _tool_started(self, event: ToolStarted) -> list[JsonPatchOp]:
        if event.tool_call_id in self._tool_index:
            return []
        ops: list[JsonPatchOp] = []
        if "step-research" not in self._step_index:
            ops += self._complete_step("step-understand")
            ops += self._add_step(
                "step-plan",
                phase="planning",
                title="Selecting relevant tools",
                status="running",
            )
            ops += self._start_step("step-plan")
            ops += self._complete_step(
                "step-plan", public_summary="Selected tools based on the request."
            )
            ops += self._add_step(
                "step-research",
                phase="research",
                title="Researching with tools",
                status="running",
            )
            ops += self._start_step("step-research")
        self._tool_index[event.tool_call_id] = len(self.state["toolCalls"])
        self._tool_started_monotonic[event.tool_call_id] = time.monotonic()
        now = _utc_now()
        self.state["toolCalls"].append(
            {
                "id": event.tool_call_id,
                "name": event.name,
                "status": "running",
                "inputPreview": preview(event.input_preview),
                "startedAt": now,
            }
        )
        ops.append(
            {
                "op": "add",
                "path": "/toolCalls/-",
                "value": self.state["toolCalls"][-1],
            }
        )
        self._bump_tool_count(ops, length=len(self.state["toolCalls"]))
        self._link_tool_to_step(ops, event.tool_call_id, event.step_id)
        return ops

    def _step_started_event(self, event: StepStarted) -> list[JsonPatchOp]:
        ops: list[JsonPatchOp] = []
        if event.step_id not in self._step_index:
            if event.phase == "planning" and "step-understand" in self._step_index:
                ops += self._complete_step("step-understand")
            ops += self._add_step(
                event.step_id,
                phase=event.phase,
                title=event.title,
                status="pending",
                parent_id=event.parent_id,
            )
        return ops + self._start_step(event.step_id)

    def _step_completed_event(self, event: StepCompleted) -> list[JsonPatchOp]:
        if event.step_id not in self._step_index:
            return []
        return self._complete_step(event.step_id, public_summary=event.public_summary)

    def _step_failed_event(self, event: StepFailed) -> list[JsonPatchOp]:
        if event.step_id not in self._step_index:
            return []
        idx = self._step_index[event.step_id]
        step = self.state["steps"][idx]
        step["status"] = "failed"
        step["finishedAt"] = _utc_now()
        step["publicSummary"] = event.public_summary
        if event.step_id in self._step_started_monotonic:
            step["durationMs"] = int(
                (time.monotonic() - self._step_started_monotonic[event.step_id]) * 1000
            )
        return [
            {"op": "add", "path": f"/steps/{idx}/{key}", "value": value}
            for key, value in step.items()
            if key in {"status", "finishedAt", "durationMs", "publicSummary"}
        ]

    # -- completion ----------------------------------------------------------

    def live_synthesis_summary(self, summary: str) -> list[JsonPatchOp]:
        """Surface the model-written process summary mid-run (finish tool).

        Creates and starts the synthesis step early so the browser sees
        synthesis running with the summary while the engine settles.
        complete_run() remains the authoritative overwrite; the same text
        makes the completion delta idempotent.
        """
        if not summary:
            return []
        ops: list[JsonPatchOp] = []
        if "step-synthesis" not in self._step_index:
            ops += self._add_step(
                "step-synthesis",
                phase="synthesis",
                title="Preparing the response",
                status="pending",
            )
        idx = self._step_index["step-synthesis"]
        if self.state["steps"][idx].get("status") != "running":
            ops += self._start_step("step-synthesis")
            idx = self._step_index["step-synthesis"]
        self.state["steps"][idx]["publicSummary"] = summary
        ops.append(
            {"op": "add", "path": f"/steps/{idx}/publicSummary", "value": summary}
        )
        return ops

    def complete_run(self, result: AgentRunResult) -> list[JsonPatchOp]:
        ops: list[JsonPatchOp] = []
        if "step-research" in self._step_index:
            ops += self._complete_step("step-research")
        else:
            ops += self._complete_step("step-understand")

        if "step-synthesis" not in self._step_index:
            ops += self._add_step(
                "step-synthesis",
                phase="synthesis",
                title="Preparing the response",
                status="running",
            )
            ops += self._start_step("step-synthesis")

        summary = result.process_summary or (
            "The agent finished without producing a final answer."
            if result.status == "failed"
            else "Composed the final answer."
        )
        ops += self._complete_step("step-synthesis", public_summary=summary)

        run = self.state["run"]
        run["status"] = "completed" if result.status == "completed" else "failed"
        run["finishedAt"] = _utc_now()
        ops.append({"op": "add", "path": "/run/status", "value": run["status"]})
        ops.append({"op": "add", "path": "/run/finishedAt", "value": run["finishedAt"]})
        if result.termination_reason:
            run["terminationReason"] = result.termination_reason
            ops.append(
                {
                    "op": "add",
                    "path": "/run/terminationReason",
                    "value": result.termination_reason,
                }
            )
        if result.error_code:
            run["errorCode"] = result.error_code
            ops.append(
                {"op": "add", "path": "/run/errorCode", "value": result.error_code}
            )

        metrics = self.state["metrics"]
        usage_metric_names = (
            ("prompt_tokens", "inputTokens"),
            ("completion_tokens", "outputTokens"),
            ("total_tokens", "totalTokens"),
        )
        for usage_name, metric_name in usage_metric_names:
            value = result.usage.get(usage_name)
            if value is not None:
                metrics[metric_name] = value
        metrics["durationMs"] = int((time.monotonic() - self._monotonic_start) * 1000)
        for key, value in metrics.items():
            if value is not None:
                ops.append({"op": "add", "path": f"/metrics/{key}", "value": value})

        for i, decision in enumerate(result.key_decisions):
            entry = {
                "id": (
                    f"decision-{self.run_id}-{i}"
                    if self._run_scoped_decisions
                    else f"decision-{i}"
                ),
                "title": decision,
                "alternatives": [],
                "status": "accepted",
            }
            self.state["decisions"].append(entry)
            ops.append({"op": "add", "path": "/decisions/-", "value": entry})

        if result.caveats:
            self.state["caveats"] = list(result.caveats)
            ops.append({"op": "add", "path": "/caveats", "value": list(result.caveats)})

        if "activeStepId" in run:
            del run["activeStepId"]
            ops.append({"op": "remove", "path": "/run/activeStepId"})

        return ops

    # -- helpers ---------------------------------------------------------

    def _add_step(
        self,
        step_id: str,
        *,
        phase: str,
        title: str,
        status: str,
        parent_id: str | None = None,
    ) -> list[JsonPatchOp]:
        self._step_index[step_id] = len(self.state["steps"])
        step = {
            "id": step_id,
            "phase": phase,
            "title": title,
            "status": status,
            "toolCallIds": [],
            "sourceIds": [],
            "artifactIds": [],
        }
        if parent_id is not None:
            step["parentId"] = parent_id
        self.state["steps"].append(step)
        return [{"op": "add", "path": "/steps/-", "value": step}]

    def _start_step(self, step_id: str) -> list[JsonPatchOp]:
        idx = self._step_index[step_id]
        step = self.state["steps"][idx]
        step["status"] = "running"
        step["startedAt"] = _utc_now()
        self._step_started_monotonic[step_id] = time.monotonic()
        self.state["run"]["activeStepId"] = step_id
        return [
            {"op": "replace", "path": f"/steps/{idx}/status", "value": "running"},
            {
                "op": "add",
                "path": f"/steps/{idx}/startedAt",
                "value": step["startedAt"],
            },
            {"op": "add", "path": "/run/activeStepId", "value": step_id},
        ]

    def _complete_step(
        self, step_id: str, public_summary: str | None = None
    ) -> list[JsonPatchOp]:
        idx = self._step_index[step_id]
        step = self.state["steps"][idx]
        step["status"] = "completed"
        step["finishedAt"] = _utc_now()
        if step_id in self._step_started_monotonic:
            step["durationMs"] = int(
                (time.monotonic() - self._step_started_monotonic[step_id]) * 1000
            )
        if public_summary:
            step["publicSummary"] = public_summary
        return [
            {"op": "add", "path": f"/steps/{idx}/{key}", "value": value}
            for key, value in step.items()
            if key in {"status", "finishedAt", "durationMs", "publicSummary"}
        ]

    def _bump_tool_count(self, ops: list[JsonPatchOp], *, length: int) -> None:
        self.state["run"]["toolCallCount"] = length
        self.state["metrics"]["toolCallCount"] = length
        ops.append({"op": "replace", "path": "/run/toolCallCount", "value": length})
        ops.append({"op": "replace", "path": "/metrics/toolCallCount", "value": length})

    def _link_tool_to_step(
        self, ops: list[JsonPatchOp], tool_call_id: str, step_id: str | None
    ) -> None:
        target = step_id if step_id in self._step_index else "step-research"
        if target not in self._step_index:
            return
        idx = self._step_index[target]
        ids = self.state["steps"][idx]["toolCallIds"]
        ids.append(tool_call_id)
        ops.append(
            {"op": "replace", "path": f"/steps/{idx}/toolCallIds", "value": list(ids)}
        )

    # -- sources & artifacts -------------------------------------------------

    def _source_discovered(self, event: SourceDiscovered) -> list[JsonPatchOp]:
        # Deduplicate by canonical URI, else by document id.
        key = canonical_source_key(event.source)
        if key in self._source_index:
            return []
        self._source_index[key] = len(self.state["sources"])
        source_id = event.source.id
        # The public state is thread-scoped. Preserve the tool id whenever it
        # is unambiguous, but disambiguate two distinct canonical documents
        # that happen to reuse an id in one thread.
        if any(source.get("id") == source_id for source in self.state["sources"]):
            from app.services.source_identity import disambiguated_source_id

            source_id = disambiguated_source_id(source_id, key)
        entry = {
            "id": source_id,
            "title": event.source.title,
            "sourceType": event.source.source_type,
            "uri": event.source.uri,
            "excerpt": preview(event.source.excerpt or ""),
            "toolCallId": event.tool_call_id,
        }
        self.state["sources"].append(entry)
        ops: list[JsonPatchOp] = [{"op": "add", "path": "/sources/-", "value": entry}]
        target_step = (
            event.step_id if event.step_id in self._step_index else "step-research"
        )
        if target_step in self._step_index:
            idx = self._step_index[target_step]
            ids = self.state["steps"][idx]["sourceIds"]
            if source_id not in ids:
                ids.append(source_id)
            ops.append(
                {"op": "replace", "path": f"/steps/{idx}/sourceIds", "value": list(ids)}
            )
        return ops

    def _artifact_started(self, event: ArtifactStarted) -> list[JsonPatchOp]:
        if event.artifact.id in self._artifact_index:
            return []
        self._artifact_index[event.artifact.id] = len(self.state["artifacts"])
        entry = {
            "id": event.artifact.id,
            "name": event.artifact.name,
            "mediaType": event.artifact.media_type,
            "status": "generating",
        }
        self.state["artifacts"].append(entry)
        return [{"op": "add", "path": "/artifacts/-", "value": entry}]

    def _artifact_ready(self, event: ArtifactReady) -> list[JsonPatchOp]:
        idx = self._artifact_index.get(event.artifact.id)
        if idx is None:
            return []
        artifact = self.state["artifacts"][idx]
        artifact["status"] = "ready"
        artifact["sizeBytes"] = event.artifact.size_bytes
        artifact["downloadUrl"] = event.download_url
        step_ops: list[JsonPatchOp] = []
        target_step = (
            event.step_id if event.step_id in self._step_index else "step-research"
        )
        if target_step in self._step_index:
            step_idx = self._step_index[target_step]
            ids = self.state["steps"][step_idx]["artifactIds"]
            if event.artifact.id not in ids:
                ids.append(event.artifact.id)
            step_ops.append(
                {
                    "op": "replace",
                    "path": f"/steps/{step_idx}/artifactIds",
                    "value": list(ids),
                }
            )
        return [
            {"op": "replace", "path": f"/artifacts/{idx}/status", "value": "ready"},
            {
                "op": "add",
                "path": f"/artifacts/{idx}/sizeBytes",
                "value": event.artifact.size_bytes,
            },
            {
                "op": "add",
                "path": f"/artifacts/{idx}/downloadUrl",
                "value": event.download_url,
            },
            *step_ops,
        ]

    def _artifact_failed(self, event: ArtifactFailed) -> list[JsonPatchOp]:
        idx = self._artifact_index.get(event.artifact_id)
        if idx is None:
            return []
        self.state["artifacts"][idx]["status"] = "failed"
        return [
            {"op": "replace", "path": f"/artifacts/{idx}/status", "value": "failed"}
        ]


def _unique_by_id(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy inherited public entities without replaying duplicate identities."""

    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        identity = str(item.get("id") or "")
        if identity and identity in seen:
            continue
        if identity:
            seen.add(identity)
        result.append(dict(item))
    return result
