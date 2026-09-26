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

_ROUTE_WRAP_CHARS = "\"'`"
"""Quotes LMs sometimes wrap around a route token."""


class ToolRoutingSignature(dspy.Signature):  # type: ignore[misc]
    """
    Select the smallest capability profile needed to resolve the request.

    direct: no external information or action is needed. Answer from your own
    knowledge.
    research: documentation, web information, time, or other read-only evidence.
    artifact: the request explicitly asks to create a managed report or artifact.
    workspace_read: repository files must be inspected without modification.
    workspace_write: repository files must be created, replaced, or edited.
    workspace_shell: commands, tests, builds, scripts, or shell operations are
    explicitly required.

    Prefer the least-privileged profile. Do not select a mutating profile merely
    because the user discusses code, commands, editing, or files conceptually.

    Deciding between direct and research: questions that ask you to explain,
    summarize, compare, translate, or describe a concept, term, framework, or
    tool are answerable from your own knowledge — choose direct — unless the
    request explicitly needs outside or up-to-date evidence (a web search, a
    documentation fetch, a lookup, the current time, or recent publications)
    or must inspect this repository's actual files (a named file path, or
    references to files in the repo, the source tree, or the test suite).
    Answering a knowledge question correctly does not require gathering
    evidence, so do not upgrade it to research.

    Deciding between workspace_write and workspace_shell: the managed file
    tools can create, read, and edit file contents, but none of them can
    delete, rename, or move a file — only the shell can. So a request to
    remove, delete, rename, or move an existing file requires workspace_shell.
    Removing or changing content inside a file (a section, a line, a typo,
    emptying the text) stays workspace_write.
    """

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
        return cast(ToolRoute, value)
    if isinstance(value, str):
        normalized = value.strip().strip(_ROUTE_WRAP_CHARS).strip().lower()
        normalized = normalized.replace("-", "_").replace(" ", "_")
        while "__" in normalized:
            normalized = normalized.replace("__", "_")
        if normalized in ROUTES:
            return cast(ToolRoute, normalized)
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
