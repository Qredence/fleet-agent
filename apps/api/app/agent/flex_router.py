"""Sandboxed, code-evolvable tool router (``dspy.Flex`` + GEPA).

The production router is a ``dspy.Predict`` over ``ToolRoutingSignature``.
This module defines the self-improvement counterpart: the same routing task
implemented as a ``dspy.Flex`` program whose source GEPA rewrites into
decomposed predictors plus plain Python.

Two properties make this safe to promote:

* The optimizer-authored source only ever runs inside ``dspy.Flex``'s Deno
  interpreter. It never executes in the host Python process, and only
  predictor construction and predictor calls bridge back to the host.
* The evolved output still flows through ``coerce_route`` downstream, so a
  degenerate candidate degrades to the least-privileged ``direct`` route
  rather than granting capability.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import dspy

from app.agent.flex_program import ensure_deno_runtime
from app.agent.routing import ToolRoutingSignature

# State format marker persisted alongside promoted router artifacts.
ROUTER_STATE_FORMAT = "fleet-agent/flex-router@1"


class FlexToolRouter(dspy.Module):  # type: ignore[misc]
    """Tool router whose implementation is optimizable code, not a prompt."""

    def __init__(self) -> None:
        super().__init__()
        # The baseline source (one Predict over the routing signature) is
        # synthesized and bound by dspy.Flex itself; every forward runs in
        # the sandboxed interpreter, baseline included.
        self.flex = dspy.Flex(ToolRoutingSignature)

    def forward(self, *, user_request: str) -> dspy.Prediction:
        return self.flex(user_request=user_request)

    def module_src(self) -> str:
        """The currently bound program source (GEPA's update unit)."""
        src = self.flex.module_src
        if not isinstance(src, str) or not src.strip():
            raise RuntimeError("Flex router has no bound module_src")
        return src


def load_flex_router(state: Mapping[str, Any]) -> FlexToolRouter:
    """Rebuild a router from a promoted state dict (no runtime checks).

    Only ``module_src`` is honored. The optimizer run's LM state is dropped
    on purpose: production always attaches the run-scoped provider from
    ``dspy.context``, never an LM embedded in a state file. Binding source
    is bookkeeping only — the Deno sandbox is needed when the router is
    *forwarded*, not when it is built.
    """
    module_src = state.get("module_src")
    if not isinstance(module_src, str) or not module_src.strip():
        raise ValueError(
            "router state must carry a non-empty 'module_src' string "
            f"(expected format {ROUTER_STATE_FORMAT!r})"
        )
    router = FlexToolRouter()
    router.flex.load_state({"module_src": module_src, "lm": None})
    return router


def load_flex_router_from_file(path: Any) -> FlexToolRouter:
    """Load a promoted router state file for engine use, fail-fast.

    Called at engine-builder construction: a missing file, malformed JSON, a
    state without source, or a missing Deno runtime surfaces at startup
    instead of on the first routed request.
    """
    import json
    from pathlib import Path

    state_path = Path(path)
    if not state_path.is_file():
        raise FileNotFoundError(
            f"FLEET_AGENT_ROUTER_STATE points at {state_path}, which does not exist"
        )
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"router state file {state_path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(state, dict):
        raise ValueError(f"router state file {state_path} must contain a JSON object")
    if not isinstance(state.get("module_src"), str) or not state["module_src"].strip():
        raise ValueError(
            f"router state file {state_path} carries no 'module_src' string "
            f"(expected format {ROUTER_STATE_FORMAT!r})"
        )
    # The evolved source executes in the Deno sandbox at request time.
    ensure_deno_runtime()
    return load_flex_router(state)
