"""Stable public error codes (plan.md Phase 11).

Clients only ever see these codes + safe messages — never stack traces,
provider payloads, or internal exception strings.
"""

ERROR_MESSAGES = {
    "agent_timeout": "The agent did not finish in time. Please try again.",
    "agent_no_output": (
        "The agent finished without producing a final answer. "
        "Please try rephrasing your request."
    ),
    "agent_parse_error": "The agent's response could not be parsed. Please try again.",
    "agent_context_limit": (
        "The conversation is too long for the model. Please start a new thread."
    ),
    "tool_timeout": "A tool call timed out.",
    "tool_failed": "A tool call failed.",
    "tool_unauthorized": "A tool was not permitted to perform that action.",
    "rate_limited": "The system is busy right now. Please retry in a moment.",
    "run_cancelled": "The run was cancelled.",
    "internal_error": "The agent run failed.",
}


def public_error(code: str | None, fallback: str = "internal_error") -> tuple[str, str]:
    """(code, safe message) — unknown codes degrade to internal_error."""
    resolved = code if code in ERROR_MESSAGES else fallback
    return resolved, ERROR_MESSAGES[resolved]
