"""Task contracts for the DSPy engine, authored as Markdown.

Prompt text lives in ``app/agent/agents/prompts/*.md`` so a reviewer reads prose
instead of a docstring. ``build_signature`` turns one Markdown body (with the
shared ``policy.md`` appended) and typed fields into a signature class of its
own; the two nodes the program needs are plain ``dspy.ReActV2`` /
``dspy.Predict`` over those classes.

Only the parts the spec layer could not express are left in Python, with the
reason named:

* ``ToolRoutingSignature`` (``routing.py``) is a conditional: choosing one of six
  least-privilege profiles is control flow.
* The evidence loop is assembled in ``program.py``, because the synthesis step
  needs ``evidence_json``, which is computed from the loop's ``dspy.History``
  rather than produced as a declared field — wiring by field name, never field
  math.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import cast

import dspy

AGENTS_DIR = Path(__file__).resolve().parent / "agents"
PROMPTS_DIR = AGENTS_DIR / "prompts"

# The synthesis predictor's public text fields. The engine streams exactly these
# with dspy.streamify listeners.
SYNTHESIS_STREAM_FIELDS = ("answer", "process_summary")


def prompt_body(name: str) -> str:
    """Body text of one Markdown prompt file, stripped."""
    path = PROMPTS_DIR / name
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"prompt file {name} is empty")
    return text


@lru_cache(maxsize=1)
def _policy_text() -> str:
    return prompt_body("policy.md")


def build_signature(
    fields: Mapping[str, tuple[object, dspy.Field]],
    instructions: str,
    *,
    signature_name: str,
    inherit_policy: bool = False,
) -> type[dspy.Signature]:
    """One signature class of its own: typed fields over instruction text.

    The Markdown body is the instruction text and reaches the model verbatim
    apart from DSPy's own ``inspect.cleandoc`` normalisation. ``inherit_policy``
    appends the shared tool-use policy, exactly as the old declarative loader
    did for its ``inherit_policy`` flags. A fresh class keeps
    ``Signature.instructions`` out of other programs: it lives on the class
    itself.
    """
    if inherit_policy:
        instructions = f"{instructions}\n\n{_policy_text()}"
    if not instructions.strip():
        raise ValueError(f"signature {signature_name!r} has no instruction text")
    return cast(
        "type[dspy.Signature]",
        dspy.make_signature(
            dict(fields), instructions=instructions, signature_name=signature_name
        ),
    )


@lru_cache(maxsize=1)
def _evidence_signature() -> type[dspy.Signature]:
    """The evidence loop's contract; no output fields by design."""
    return build_signature(
        {
            "user_request": (str, dspy.InputField(desc="The user's request.")),
        },
        prompt_body("evidence.md"),
        signature_name="Evidence",
        inherit_policy=True,
    )


@lru_cache(maxsize=1)
def _synthesis_signature() -> type[dspy.Signature]:
    """The synthesis predictor's contract over the gathered evidence."""
    return build_signature(
        {
            "user_request": (str, dspy.InputField(desc="The user's request.")),
            "output_intent": (
                str,
                dspy.InputField(desc="Validated output mode: none or managed_report."),
            ),
            "evidence_json": (
                str,
                dspy.InputField(desc="Bounded successful and failed evidence."),
            ),
            "history": (
                dspy.History,
                dspy.InputField(desc="Prior conversation turns."),
            ),
            "answer": (
                str,
                dspy.OutputField(desc="Direct final answer to the user."),
            ),
            "process_summary": (
                str,
                dspy.OutputField(desc="Concise user-safe process summary."),
            ),
            "key_decisions": (
                list[str],
                dspy.OutputField(desc="Important decisions made."),
            ),
            "caveats": (
                list[str],
                dspy.OutputField(desc="Remaining uncertainty or limitations."),
            ),
        },
        prompt_body("synthesize.md"),
        signature_name="Synthesis",
        inherit_policy=True,
    )


def build_synthesizer() -> dspy.Module:
    """Build the synthesis node: one ``Predict`` over the Markdown text."""
    return dspy.Predict(_synthesis_signature())


def build_gatherer(tools: Sequence[dspy.Tool], max_iters: int) -> dspy.Module:
    """Build the evidence loop: one ``ReActV2`` over the Markdown contract.

    The run's least-privilege profile supplies the tools, so a route still
    cannot reach a tool outside its profile. ``max_iters`` binds here -
    not at a per-node default - because the program owns the operator's loop
    bound. Fresh instances per call because tools carry run-scoped state (an
    event bus, a thread id); the signature class itself is shared, which is
    safe now that no optimizer writes back into it.
    """
    return dspy.ReActV2(_evidence_signature(), tools=list(tools), max_iters=max_iters)
