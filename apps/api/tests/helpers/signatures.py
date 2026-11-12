"""The reference ReActV2 task contract used by the contract tests.

This is not on the production request path: the live evidence loop builds one
signature per capability profile from ``app/agent/agents/prompts/*.md``. It stays
here so the ReActV2-level contract tests (submit-tool shape, adapter behaviour,
tool-call coercion, streaming) exercise a stable signature.

Its tool-use policy is the SAME Markdown the live loop inherits, so the text has
exactly one source.
"""

from __future__ import annotations

import dspy

from app.agent.signature import build_signature

AgentSignature: type[dspy.Signature] = build_signature(
    {
        "user_request": (str, dspy.InputField(desc="The user's request.")),
        "answer": (
            str,
            dspy.OutputField(desc="Direct final answer to the user."),
        ),
        "process_summary": (
            str,
            dspy.OutputField(desc="Concise user-facing summary of the approach taken."),
        ),
        "key_decisions": (
            list[str],
            dspy.OutputField(desc="Important decisions made during the process."),
        ),
        "caveats": (
            list[str],
            dspy.OutputField(desc="Remaining uncertainty, limitations, or risks."),
        ),
    },
    (
        "Resolve the user's request using available tools when necessary.\n\n"
        "Produce a direct final answer and a concise, user-safe account of the\n"
        "approach and decisions. Do not expose hidden reasoning."
    ),
    signature_name="AgentSignature",
    inherit_policy=True,
)
