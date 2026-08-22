"""The task contract for the DSPy ReActV2 engine.

Outputs are explicit USER-FACING fields: a direct answer plus a concise,
user-safe account of approach, decisions, and caveats. They are model-written
public text — never derived from or containing raw reasoning traces.
"""

import dspy


class AgentSignature(dspy.Signature):  # type: ignore[misc]  # dspy is untyped
    """
    Resolve the user's request using available tools when necessary.

    Produce a direct final answer and a concise, user-safe account
    of the approach and decisions. Do not expose hidden reasoning.
    """

    user_request: str = dspy.InputField(desc="The user's request.")

    answer: str = dspy.OutputField(desc="Direct final answer to the user.")
    process_summary: str = dspy.OutputField(
        desc="Concise user-facing summary of the approach taken."
    )
    key_decisions: list[str] = dspy.OutputField(
        desc="Important decisions made during the process."
    )
    caveats: list[str] = dspy.OutputField(
        desc="Remaining uncertainty, limitations, or risks."
    )
