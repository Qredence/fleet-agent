"""Shared extraction of message text and conversation history from RunAgentInput."""

from collections.abc import Sequence
from typing import Any

import dspy
from ag_ui.core import RunAgentInput
from ag_ui.core.types import TextInputContent


def extract_message_text(content: Any) -> str:
    """Extract plain text from string or structured content parts."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, TextInputContent):
                parts.append(part.text)
            elif isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text", "")
                if text:
                    parts.append(text)
            elif isinstance(part, str):
                parts.append(part)
        return " ".join(parts).strip()
    return ""


def last_user_text(input_data: RunAgentInput) -> str:
    for message in reversed(input_data.messages):
        if message.role != "user":
            continue
        return extract_message_text(message.content)
    return ""


def history_from_agui_messages(messages: Sequence[Any]) -> dspy.History | None:
    """Reconstruct prior conversation turns from AG-UI messages."""
    turns: list[dict[str, Any]] = []
    pending_user: str | None = None
    for msg in messages:
        role = getattr(msg, "role", None) or (
            msg.get("role") if isinstance(msg, dict) else None
        )
        raw_content = (
            getattr(msg, "content", None)
            if not isinstance(msg, dict)
            else msg.get("content")
        )
        text = extract_message_text(raw_content)
        if role == "user":
            pending_user = text
        elif role == "assistant" and pending_user:
            if text:
                turns.append({"user_request": pending_user, "answer": text})
            pending_user = None
    if not turns:
        return None
    return dspy.History(messages=turns)
