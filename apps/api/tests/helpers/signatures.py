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

from app.agent.signature import AGENTS_DIR
from app.agent.spec import (
    FieldSpec,
    SignatureSpec,
    build_signature,
    read_markdown,
)

_AGENT_SPEC = SignatureSpec(
    name="AgentSignature",
    inputs=[
        FieldSpec(name="user_request", type="str", description="The user's request.")
    ],
    outputs=[
        FieldSpec(
            name="answer", type="str", description="Direct final answer to the user."
        ),
        FieldSpec(
            name="process_summary",
            type="str",
            description="Concise user-facing summary of the approach taken.",
        ),
        FieldSpec(
            name="key_decisions",
            type="list[str]",
            description="Important decisions made during the process.",
        ),
        FieldSpec(
            name="caveats",
            type="list[str]",
            description="Remaining uncertainty, limitations, or risks.",
        ),
    ],
    instructions=(
        "Resolve the user's request using available tools when necessary.\n\n"
        "Produce a direct final answer and a concise, user-safe account of the\n"
        "approach and decisions. Do not expose hidden reasoning."
    ),
    inherit_policy=True,
)

AgentSignature: type[dspy.Signature] = build_signature(
    _AGENT_SPEC,
    policy=read_markdown(AGENTS_DIR / "prompts" / "policy.md")[1],
    base=AGENTS_DIR,
)
