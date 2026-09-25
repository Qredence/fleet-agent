"""Approval policy for gated tools.

Approval is a DECISION made before a run starts, not a control-flow primitive
inside the reasoning loop. A tool whose policy sets ``requires_approval`` is
simply withheld from the model unless the run authorizes it up front, so the
model can never call a mutating tool that was not approved in advance.

The previous design paused ``dspy.ReActV2`` mid-loop to ask a human. That needed
an 846-line fork of the loop over four private DSPy symbols, a hard version pin, a
durable checkpoint table, a boot-time database dependency - and it covered a
checkpoint with a five-minute TTL that was never written. Withholding the tool is
strictly safer: an unauthorized tool is not merely declined, it is never offered.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.agent.tool_registry import ToolMetadata

APPROVAL_KEY = "approvedTools"
"""Request key, read from ``RunAgentInput.forwardedProps``."""

WILDCARD = "*"
"""Value meaning "this run authorizes every gated tool"."""


def approved_tool_names(forwarded_props: Any) -> frozenset[str] | None:
    """Read one run's approval list from the request's forwarded properties.

    Accepts ``"*"``/``true`` for everything, a single tool name, or a list of
    names. Anything else, including a missing key, means no approval was given -
    the fail-closed default.
    """
    if not isinstance(forwarded_props, Mapping):
        return None
    raw = forwarded_props.get(APPROVAL_KEY)
    if raw is None:
        return None
    if raw is True or raw == WILDCARD:
        return frozenset({WILDCARD})
    if isinstance(raw, str):
        return frozenset({raw}) if raw else None
    if isinstance(raw, (list, tuple, set, frozenset)):
        names = {str(item) for item in raw if str(item)}
        return frozenset(names) if names else None
    return None


def offered_tool_names(
    policy: Mapping[str, ToolMetadata],
    approved: frozenset[str] | None,
) -> set[str]:
    """Every registered tool except the gated ones this run did not authorize."""
    granted = approved or frozenset()
    wildcard = WILDCARD in granted
    return {
        name
        for name, metadata in policy.items()
        if not metadata.requires_approval or wildcard or name in granted
    }
