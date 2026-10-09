"""Public process state: the vocabulary, the reducer, and the patch diff.

The reducer owns one mutable ``AgentWorkspaceState`` dict per run. Consumers
(the AG-UI mapper and the coordinators) read it and apply the JSON-Patch deltas
it returns; nothing else mutates it, so the state streamed to the browser and
the snapshot persisted for reload can never disagree.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any

from app.agent.engine import AgentRunResult
from app.agent.instrumented import preview
from app.contracts.domain import (
    ArtifactFailed,
    ArtifactReady,
    ArtifactStarted,
    FinalFieldsReady,
    InlineDataEvent,
    SourceDiscovered,
    StepCompleted,
    StepFailed,
    StepStarted,
    SynthesisTokenDelta,
    ToolCompleted,
    ToolFailed,
    ToolStarted,
)
from app.kernel.identity import canonical_source_key, disambiguated_source_id

# One RFC 6902 JSON Patch operation, as carried by AG-UI STATE_DELTA events.
JsonPatchOp = dict[str, Any]


def _escape(token: str) -> str:
    """JSON Pointer escaping (RFC 6901) for one object key."""
    return token.replace("~", "~0").replace("/", "~1")


def state_diff(before: Any, after: Any, *, path: str = "") -> list[JsonPatchOp]:
    """Operations that turn ``before`` into ``after`` (RFC 6902).

    Dicts diff key by key; lists and scalars are reported as one ``replace`` of
    the new value. Whole-value list patches are deliberate: an incremental
    ``add .../-`` is not idempotent, so a client that re-applies a delta would
    duplicate an entry. The reducer mutates state and calls this once per event,
    so the wire delta is derived from the same object that gets persisted
    instead of being maintained a second time by hand.
    """
    if isinstance(before, dict) and isinstance(after, dict):
        ops: list[JsonPatchOp] = []
        for key, new_value in after.items():
            child = f"{path}/{_escape(str(key))}"
            if key in before:
                ops += state_diff(before[key], new_value, path=child)
            else:
                ops.append({"op": "add", "path": child, "value": new_value})
        for key in before:
            if key not in after:
                ops.append({"op": "remove", "path": f"{path}/{_escape(str(key))}"})
        return ops
    if before != after:
        return [{"op": "replace", "path": path, "value": after}]
    return []


AnyDomainEvent = (
    InlineDataEvent
    | ToolStarted
    | ToolCompleted
    | ToolFailed
    | SourceDiscovered
    | StepStarted
    | StepCompleted
    | StepFailed
    | ArtifactStarted
    | ArtifactReady
    | ArtifactFailed
    | FinalFieldsReady
    | SynthesisTokenDelta
)


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
            "schemaVersion": 2,
            "threadId": thread_id,
            "run": {
                "id": run_id,
                "status": "running",
                "saveStatus": "pending",
                "programVersion": "fleet-agent@2",
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

    # -- lifecycle ---------------------------------------------------------

    def begin(self) -> list[JsonPatchOp]:
        """RUN_STARTED + snapshot are emitted by the coordinator; this is the
        first delta: understanding starts."""
        return self._diff(lambda: self._start_step("step-understand"))

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
        return self._diff(lambda: self._reduce(event))

    def _reduce(
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
    ) -> None:
        if isinstance(event, ToolStarted):
            self._tool_started(event)
        elif isinstance(event, StepStarted):
            self._step_started_event(event)
        elif isinstance(event, StepCompleted):
            self._step_completed_event(event)
        elif isinstance(event, StepFailed):
            self._step_failed_event(event)
        elif isinstance(event, ToolCompleted | ToolFailed):
            self._tool_settled(event)
        elif isinstance(event, SourceDiscovered):
            self._source_discovered(event)
        elif isinstance(event, ArtifactStarted):
            self._artifact_started(event)
        elif isinstance(event, ArtifactReady):
            self._artifact_ready(event)
        else:
            self._artifact_failed(event)

    def _diff(self, change: Callable[[], None]) -> list[JsonPatchOp]:
        """Apply one state change and report it as JSON Patch operations.

        Every mutator below writes state only; this is the single place that
        turns a change into a wire delta, so a field can never be updated in
        state but forgotten in the patch (or the other way round).
        """
        before = deepcopy(self.state)
        change()
        return state_diff(before, self.state)

    # -- tool, step and run mutators -----------------------------------------

    def _tool_settled(self, event: ToolCompleted | ToolFailed) -> None:
        idx = self._tool_index.get(event.tool_call_id)
        if idx is None:
            return
        tool = self.state["toolCalls"][idx]
        tool["status"] = "completed" if isinstance(event, ToolCompleted) else "failed"
        tool["finishedAt"] = _utc_now()
        tool["durationMs"] = event.duration_ms
        if isinstance(event, ToolCompleted):
            tool["outputPreview"] = preview(event.output_preview)
        else:
            tool["errorMessage"] = event.error_message

    def _tool_started(self, event: ToolStarted) -> None:
        if event.tool_call_id in self._tool_index:
            return
        if "step-research" not in self._step_index:
            self._complete_step("step-understand")
            self._add_step(
                "step-research",
                phase="research",
                title="Researching with tools",
                status="running",
            )
            self._start_step("step-research")
        self._tool_index[event.tool_call_id] = len(self.state["toolCalls"])
        self.state["toolCalls"].append(
            {
                "id": event.tool_call_id,
                "name": event.name,
                "status": "running",
                "inputPreview": preview(event.input_preview),
                "startedAt": _utc_now(),
            }
        )
        self._bump_tool_count(length=len(self.state["toolCalls"]))
        self._link_tool_to_step(event.tool_call_id, event.step_id)

    def _step_started_event(self, event: StepStarted) -> None:
        if event.step_id not in self._step_index:
            if event.phase == "planning" and "step-understand" in self._step_index:
                self._complete_step("step-understand")
            self._add_step(
                event.step_id,
                phase=event.phase,
                title=event.title,
                status="pending",
                parent_id=event.parent_id,
            )
        self._start_step(event.step_id)

    def _step_completed_event(self, event: StepCompleted) -> None:
        if event.step_id not in self._step_index:
            return
        self._complete_step(event.step_id, public_summary=event.public_summary)

    def _step_failed_event(self, event: StepFailed) -> None:
        idx = self._step_index.get(event.step_id)
        if idx is None:
            return
        step = self.state["steps"][idx]
        step["status"] = "failed"
        step["finishedAt"] = _utc_now()
        step["publicSummary"] = event.public_summary
        if event.step_id in self._step_started_monotonic:
            step["durationMs"] = int(
                (time.monotonic() - self._step_started_monotonic[event.step_id]) * 1000
            )

    # -- completion ----------------------------------------------------------

    def live_synthesis_summary(self, summary: str) -> list[JsonPatchOp]:
        """Publish a model-written process summary while the run is in progress."""
        if not summary:
            return []
        return self._diff(lambda: self._set_live_summary(summary))

    def _set_live_summary(self, summary: str) -> None:
        if "step-synthesis" not in self._step_index:
            self._add_step(
                "step-synthesis",
                phase="synthesis",
                title="Preparing the response",
                status="pending",
            )
        idx = self._step_index["step-synthesis"]
        if self.state["steps"][idx].get("status") != "running":
            self._start_step("step-synthesis")
            idx = self._step_index["step-synthesis"]
        self.state["steps"][idx]["publicSummary"] = summary

    def complete_run(self, result: AgentRunResult) -> list[JsonPatchOp]:
        """Publish the final status, summary, metrics, decisions and caveats."""
        return self._diff(lambda: self._finalize(result))

    def _finalize(self, result: AgentRunResult) -> None:
        if "step-research" in self._step_index:
            self._complete_step("step-research")
        else:
            self._complete_step("step-understand")
        if "step-synthesis" not in self._step_index:
            self._add_step(
                "step-synthesis",
                phase="synthesis",
                title="Preparing the response",
                status="running",
            )
            self._start_step("step-synthesis")
        summary = result.process_summary or (
            "The agent finished without producing a final answer."
            if result.status == "failed"
            else "Composed the final answer."
        )
        self._complete_step("step-synthesis", public_summary=summary)

        run = self.state["run"]
        run["status"] = "completed" if result.status == "completed" else "failed"
        run["finishedAt"] = _utc_now()
        if result.termination_reason:
            run["terminationReason"] = result.termination_reason
        if result.error_code:
            run["errorCode"] = result.error_code
        if result.evidence_status:
            run["evidenceStatus"] = result.evidence_status
        if result.evidence_reason:
            run["evidenceStopReason"] = result.evidence_reason

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

        for i, decision in enumerate(result.key_decisions):
            self.state["decisions"].append(
                {
                    "id": (
                        f"decision-{self.run_id}-{i}"
                        if self._run_scoped_decisions
                        else f"decision-{i}"
                    ),
                    "title": decision,
                    "alternatives": [],
                    "status": "accepted",
                }
            )

        if result.caveats:
            self.state["caveats"] = list(result.caveats)
        run.pop("activeStepId", None)

    def _add_step(
        self,
        step_id: str,
        *,
        phase: str,
        title: str,
        status: str,
        parent_id: str | None = None,
    ) -> None:
        self._step_index[step_id] = len(self.state["steps"])
        step: dict[str, Any] = {
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

    def _start_step(self, step_id: str) -> None:
        idx = self._step_index[step_id]
        step = self.state["steps"][idx]
        step["status"] = "running"
        step["startedAt"] = _utc_now()
        self._step_started_monotonic[step_id] = time.monotonic()
        self.state["run"]["activeStepId"] = step_id

    def _complete_step(self, step_id: str, public_summary: str | None = None) -> None:
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

    def _bump_tool_count(self, *, length: int) -> None:
        self.state["run"]["toolCallCount"] = length
        self.state["metrics"]["toolCallCount"] = length

    def _link_tool_to_step(self, tool_call_id: str, step_id: str | None) -> None:
        target = step_id if step_id in self._step_index else "step-research"
        if target not in self._step_index:
            return
        self.state["steps"][self._step_index[target]]["toolCallIds"].append(
            tool_call_id
        )

    # -- sources & artifacts -------------------------------------------------

    def _source_discovered(self, event: SourceDiscovered) -> None:
        # Deduplicate by canonical URI, else by document id.
        key = canonical_source_key(event.source)
        if key in self._source_index:
            return
        self._source_index[key] = len(self.state["sources"])
        source_id = event.source.id
        # The public state is thread-scoped. Preserve the tool id whenever it
        # is unambiguous, but disambiguate two distinct canonical documents
        # that happen to reuse an id in one thread.
        if any(source.get("id") == source_id for source in self.state["sources"]):
            source_id = disambiguated_source_id(source_id, key)
        self.state["sources"].append(
            {
                "id": source_id,
                "title": event.source.title,
                "sourceType": event.source.source_type,
                "uri": event.source.uri,
                "excerpt": preview(event.source.excerpt or ""),
                "toolCallId": event.tool_call_id,
            }
        )
        target_step = (
            event.step_id if event.step_id in self._step_index else "step-research"
        )
        if target_step in self._step_index:
            ids = self.state["steps"][self._step_index[target_step]]["sourceIds"]
            if source_id not in ids:
                ids.append(source_id)

    def _artifact_started(self, event: ArtifactStarted) -> None:
        if event.artifact.id in self._artifact_index:
            return
        self._artifact_index[event.artifact.id] = len(self.state["artifacts"])
        self.state["artifacts"].append(
            {
                "id": event.artifact.id,
                "name": event.artifact.name,
                "mediaType": event.artifact.media_type,
                "status": "generating",
            }
        )

    def _artifact_ready(self, event: ArtifactReady) -> None:
        idx = self._artifact_index.get(event.artifact.id)
        if idx is None:
            return
        artifact = self.state["artifacts"][idx]
        artifact["status"] = "ready"
        artifact["sizeBytes"] = event.artifact.size_bytes
        artifact["downloadUrl"] = event.download_url
        target_step = (
            event.step_id if event.step_id in self._step_index else "step-research"
        )
        if target_step in self._step_index:
            ids = self.state["steps"][self._step_index[target_step]]["artifactIds"]
            if event.artifact.id not in ids:
                ids.append(event.artifact.id)

    def _artifact_failed(self, event: ArtifactFailed) -> None:
        idx = self._artifact_index.get(event.artifact_id)
        if idx is None:
            self._artifact_index[event.artifact_id] = len(self.state["artifacts"])
            self.state["artifacts"].append(
                {
                    "id": event.artifact_id,
                    "name": event.name,
                    "mediaType": event.media_type,
                    "status": "failed",
                }
            )
            return
        artifact = self.state["artifacts"][idx]
        artifact["status"] = "failed"
        artifact.pop("downloadUrl", None)


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
