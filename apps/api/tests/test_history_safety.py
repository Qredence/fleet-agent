import pytest
from pydantic import ValidationError

from app.api.threads import _safe_bootstrap_agent_state
from app.kernel.history_safety import MessageWrite, sanitize_message_content


def _message(content: dict) -> dict:
    return {"format": "aui/v0", "content": {"role": "assistant", **content}}


@pytest.mark.parametrize("key", ["partType", "contentType"])
def test_reasoning_part_descriptors_are_rejected(key: str) -> None:
    with pytest.raises(ValidationError):
        MessageWrite.model_validate(
            _message({"parts": [{key: "reasoning", "text": "private thought"}]})
        )


def test_excessive_nesting_is_rejected_without_recursion_error() -> None:
    nested: object = "text"
    for _ in range(2000):
        nested = {"value": nested}

    with pytest.raises(ValidationError, match="too deeply nested"):
        MessageWrite.model_validate(_message({"parts": [nested]}))


def test_sanitizer_handles_cycles_without_recursion_error() -> None:
    value: dict[str, object] = {"role": "assistant"}
    value["cycle"] = value

    sanitized = sanitize_message_content(value)
    assert sanitized == {"role": "assistant"}


def test_bootstrap_state_is_strictly_safe_and_caps_source_excerpt() -> None:
    state = {
        "schemaVersion": 1,
        "threadId": "thread-1",
        "run": {
            "id": "run-1",
            "status": "completed",
            "toolCallCount": 0,
            "errorCode": "database password=secret",
        },
        "steps": [],
        "decisions": [],
        "toolCalls": [],
        "sources": [
            {
                "id": "source-1",
                "title": "Doc",
                "sourceType": "web",
                "excerpt": "x" * 1000,
            }
        ],
        "artifacts": [],
        "metrics": {"toolCallCount": 0},
        "next_thought": "private reasoning",
    }

    safe = _safe_bootstrap_agent_state(state, thread_id="thread-1")
    assert safe is not None
    assert "next_thought" not in str(safe)
    assert "errorCode" not in safe["run"]
    assert len(safe["sources"][0]["excerpt"]) == 300


def test_sanitizer_scrubs_secrets_and_preserves_valid_json_values() -> None:
    value = {
        "role": "assistant",
        "parts": [
            {"type": "text", "text": "Use key sk-proj-4ZqY9wF2xQ7bR1mK3nD8vT5c"},
            {"type": "tool-call", "argsText": '{"api_key": "Z9y8x7w6v5u4t3s2r1q0"}'},
        ],
    }

    sanitized = sanitize_message_content(value)
    assert sanitized["parts"][0]["text"] == "Use key [redacted]"
    assert sanitized["parts"][1]["argsText"] == '{"api_key": "[redacted]"}'
