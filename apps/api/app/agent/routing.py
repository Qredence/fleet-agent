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
    route: ToolRoute = dspy.OutputField(
        desc="The minimum capability profile required for the task."
    )


def coerce_route(value: object) -> ToolRoute:
    """Convert an untrusted router output to a least-privileged route."""
    if value in ROUTES:
        return value
    return "direct"
