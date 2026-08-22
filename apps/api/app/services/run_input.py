"""Shared extraction of the latest user text from a RunAgentInput."""

from ag_ui.core import RunAgentInput
from ag_ui.core.types import TextInputContent


def last_user_text(input_data: RunAgentInput) -> str:
    for message in reversed(input_data.messages):
        if message.role != "user":
            continue
        content = message.content
        if isinstance(content, str):
            return content
        return " ".join(
            part.text for part in content if isinstance(part, TextInputContent)
        )
    return ""
