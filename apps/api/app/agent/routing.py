"""Capability routing for the production DSPy program."""

from typing import Literal

import dspy

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


class ToolRoutingSignature(dspy.Signature):  # type: ignore[misc]
    """
    Select the smallest capability profile needed to resolve the request.

    direct: no external information or action is needed.
    research: documentation, web information, time, or other read-only evidence.
    artifact: the request explicitly asks to create a managed report or artifact.
    workspace_read: repository files must be inspected without modification.
    workspace_write: repository files must be created, replaced, or edited.
    workspace_shell: commands, tests, builds, scripts, or shell operations are
    explicitly required.

    Prefer the least-privileged profile. Do not select a mutating profile merely
    because the user discusses code, commands, editing, or files conceptually.
    """

    user_request: str = dspy.InputField(desc="The user's current request.")
    route: ToolRoute = dspy.OutputField(
        desc="The minimum capability profile required for the task."
    )


def coerce_route(value: object) -> ToolRoute:
    """Convert an untrusted router output to a least-privileged route."""
    if value in ROUTES:
        return value
    return "direct"
