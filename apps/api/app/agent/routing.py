"""Capability routing for the production DSPy program.

The router is an ordinary ``dspy.Predict``; the conditional that dispatches on
its answer lives in ``program.py``. This module owns the routing contract, the
fail-closed coercion of an untrusted answer, and the artifact contract an offline
optimizer writes when it promotes improved router instructions.
"""

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

import dspy

from app.agent.tool_registry import ToolCapability

logger = logging.getLogger(__name__)

ROUTER_STATE_FORMAT = "fleet-agent/router-state@1"
"""Format tag of a promoted router artifact; ``evals/optimize.py`` writes it."""

ToolRoute = Literal[
    "direct",
    "research",
    "artifact",
    "workspace_read",
    "workspace_write",
    "workspace_shell",
]

ROUTES: tuple[ToolRoute, ...] = (
    "direct",
    "research",
    "artifact",
    "workspace_read",
    "workspace_write",
    "workspace_shell",
)

ROUTE_CAPABILITIES: dict[ToolRoute, frozenset[ToolCapability]] = {
    "direct": frozenset(),
    "research": frozenset({"retrieval", "utility"}),
    "artifact": frozenset({"retrieval", "utility", "artifact"}),
    "workspace_read": frozenset({"retrieval", "utility", "workspace_read"}),
    "workspace_write": frozenset(
        {"retrieval", "utility", "workspace_read", "workspace_write"}
    ),
    "workspace_shell": frozenset(
        {"retrieval", "utility", "workspace_read", "workspace_write", "shell"}
    ),
}

_ROUTE_WRAP_CHARS = "\"'`"
"""Quotes LMs sometimes wrap around a route token."""


class ToolRoutingSignature(dspy.Signature):  # type: ignore[misc]
    """Select the least-privileged route that can fulfill the current request.

    Choose exactly one route: direct, research, artifact, workspace_read,
    workspace_write, or workspace_shell.

    Route definitions:
    - direct: Answer from the conversation or your own knowledge; no external
      lookup, repository inspection, or action is needed.
    - research: Obtain read-only evidence from the web, product documentation,
      current-time sources, or other external sources. Searching or fetching
      product documentation is research, not repository inspection.
    - artifact: Gather external research evidence to create or export a managed
      report. Use this when the user requests a standalone managed report and
      the needed evidence is not already supplied. Do not inspect the workspace
      unless the user also asks for repository evidence.
    - workspace_read: Inspect actual repository files, source trees, or test
      suites without changing them.
    - workspace_write: Create, replace, or edit repository file contents.
    - workspace_shell: Run commands, tests, builds, scripts, or other shell
      operations; also use it to delete, rename, or move files.

    Decision rules:
    1. Use direct for ordinary knowledge questions: explaining, summarizing,
       comparing, translating, or describing a concept, term, framework, or
       tool. Do not use research merely because external evidence could
       improve an answer.
    2. Use research when the request explicitly needs a web search,
       documentation lookup or fetch, current time, recent publications, or
       other up-to-date/external evidence. A request about product
       documentation remains research even if it mentions documentation,
       manuals, or guides; it is not workspace_read unless it asks to inspect
       files in this repository.
    3. Use workspace_read only when the request requires findings from actual
       repository contents, for example when it names a repository file or asks
       about this repo, its source tree, or its test suite. A general question
       about a tool or its documentation does not qualify.
    4. Use artifact for a requested managed report or downloadable report that
       requires new external research. For a report based on repository
       contents, use workspace_read (or the explicitly required mutation
       route) and set output_intent=managed_report. Exporting a report does not
       itself require workspace mutation privileges.
    5. Use workspace_write only when repository file contents must be created,
       replaced, or edited. Editing or emptying content within a file is
       workspace_write.
    6. Use workspace_shell only when shell execution is explicitly required, or
       an existing file must be deleted, renamed, or moved. Read-only file
       searches and listings requested for findings use workspace_read, not
       workspace_shell.
    7. Do not infer a need for mutation or shell access merely because the user
       discusses code, commands, editing, or files conceptually. Choose the
       smallest profile that satisfies the actual request.

    Use conversation context and already-supplied evidence. A follow-up that
    only reformats or exports a previous answer uses direct; do not re-inspect
    earlier files unless the current request asks for a new check, correction,
    refresh, or change. A request to "report" findings in chat is not a request
    to create a managed report: set output_intent=none unless the user asks for
    a report artifact or downloadable file.
    """

    conversation_context: str = dspy.InputField(
        desc="Bounded selected-branch conversation context, newest turns first.",
        default="",
    )
    output_intent: str = dspy.OutputField(
        desc=(
            "none or managed_report. Select managed_report for a requested "
            "downloadable report; select its evidence route independently."
        )
    )
    user_request: str = dspy.InputField(desc="The user's current request.")
    route: str = dspy.OutputField(
        desc="The minimum capability profile required for the task."
    )


def coerce_route(value: object) -> ToolRoute:
    """Convert an untrusted router output to a least-privileged route.

    Exact ``ROUTES`` members pass through. Strings are normalized for common
    LM surface noise (whitespace, case, hyphens/spaces as separators, wrapping
    quotes) before membership is checked. Invented names and non-strings
    fail-closed to ``direct`` — coerce never elevates privilege via aliases.
    """
    if value in ROUTES:
        return value
    if isinstance(value, str):
        normalized = value.strip().strip(_ROUTE_WRAP_CHARS).strip().lower()
        normalized = normalized.replace("-", "_").replace(" ", "_")
        while "__" in normalized:
            normalized = normalized.replace("__", "_")
        if normalized in ROUTES:
            return normalized
    return "direct"


@lru_cache(maxsize=8)
def routing_signature(instructions: str | None = None) -> type[dspy.Signature]:
    """Return the routing contract, optionally carrying promoted instructions.

    A fresh class per instruction set: ``Signature.instructions`` lives on the
    class itself, so overriding the shared ``ToolRoutingSignature`` would leak
    one promoted artifact into every other program in the process.
    ``with_instructions`` keeps the declared fields and their types.
    """
    if not instructions:
        return ToolRoutingSignature
    # dspy is untyped here: with_instructions returns a new Signature class.
    promoted = ToolRoutingSignature.with_instructions(instructions)
    return cast("type[dspy.Signature]", promoted)


def read_router_state(path: str | Path) -> str | None:
    """Return the promoted router instructions from ``path``, or ``None``.

    A malformed or unrecognized artifact is refused loudly at engine-build time
    rather than silently ignored: an operator who pinned a state file expects it
    to be in effect.
    """
    state_path = Path(path)
    if not state_path.is_file():
        raise FileNotFoundError(f"router state file not found: {state_path}")
    try:
        payload: Any = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"router state file is not readable JSON: {error}") from error
    if not isinstance(payload, dict):
        raise ValueError("router state must be a JSON object")
    if payload.get("format") != ROUTER_STATE_FORMAT:
        raise ValueError(
            f"router state format {payload.get('format')!r} is not "
            f"{ROUTER_STATE_FORMAT!r}"
        )
    instructions = payload.get("router_instructions")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValueError("router state carries no router_instructions text")
    return instructions
