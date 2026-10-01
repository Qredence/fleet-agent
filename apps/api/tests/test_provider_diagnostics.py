import json

import pytest

from app.agent.provider_diagnostics import rejection_facts, request_structure


@pytest.mark.parametrize("nested", [False, True])
def test_full_error_envelope_redacts_echoes(nested):
    key = "user_fixture_secret"
    prompt = "Private user prompt fixture content"
    reasoning = "Private reasoning fixture content"
    output = "Private tool output fixture content"
    body = {
        "messages": [
            {"content": prompt},
            {"reasoning_content": reasoning},
            {"role": "tool", "content": output},
        ]
    }
    error = {"error": {"message": f"{prompt} {reasoning} {output} Bearer {key}"}}
    if nested:
        error = {"error": {"cause": {"responseBody": json.dumps(error)}}}
    result = json.dumps(rejection_facts(json.dumps(error).encode(), body, (key,)))
    for secret in (key, prompt, reasoning, output):
        assert secret not in result


def test_long_envelope_preserves_rejection_after_500_bytes():
    payload = {
        "padding": "x" * 1000,
        "error": {
            "message": "Tool result pairing is invalid",
            "code": "invalid_request_error",
        },
    }
    facts = rejection_facts(json.dumps(payload).encode(), {}, ())
    assert "details" not in facts
    assert "invalid" in facts["mentioned_rules"]
    assert facts["codes"] == ["invalid_request_error"]


@pytest.mark.parametrize("encoding", ["double_json", "trailing_label", "nested_data"])
def test_gateway_envelope_variants_preserve_inner_rejection(encoding):
    error = {"error": {"message": "Thinking mode does not support this tool_choice"}}
    if encoding == "double_json":
        message = json.dumps(json.dumps(error))
    elif encoding == "trailing_label":
        message = json.dumps(error) + " (fixture-model)"
    else:
        message = {"data": error}
    facts = rejection_facts(
        json.dumps({"error": {"message": message}}).encode(), {}, ()
    )
    assert "details" not in facts
    assert facts["mentioned_fields"] == ["tool_choice"]
    assert "does not support" in facts["mentioned_rules"]


def test_forced_submit_stage_keeps_all_declared_tools():
    facts = request_structure(
        {
            "tools": [
                {"function": {"name": "lookup"}},
                {"function": {"name": "submit"}},
            ],
            "tool_choice": {"type": "function", "function": {"name": "submit"}},
        }
    )
    assert facts["stage"] == "forced_submission"
    assert facts["tool_choice"] == "named_submit"
    assert facts["tool_count"] == 2


def test_request_id_rejects_content_and_credential_shapes():
    from app.agent.provider_diagnostics import _request_id

    assert _request_id("req-f7b32") == "req-f7b32"
    for value in ("private content", "sk-seeded", "user_seeded", "x" * 129, None):
        assert _request_id(value) is None


def test_malformed_envelope_never_logs_raw_content():
    facts = rejection_facts(b"<html>private-secret</html>", {}, ())
    assert facts["envelope"] == "non_json"
    assert "private-secret" not in json.dumps(facts)


def test_request_structure_has_pairing_without_tool_content():
    body = {
        "messages": [
            {
                "role": "assistant",
                "content": None,
                "reasoning_content": "private thought",
                "tool_calls": [
                    {"id": "call-a", "function": {"arguments": "private args"}}
                ],
            },
            {"role": "tool", "tool_call_id": "call-a", "content": "private result"},
        ],
        "tools": [{"function": {"name": "lookup"}}],
    }
    result = request_structure(body)
    assert result["stage"] == "evidence_gathering"
    assert result["messages"][0]["call_ids"][0] == result["messages"][1]["result_id"]
    assert "private" not in json.dumps(result)


def test_default_diagnostics_are_disabled():
    from app.settings import Settings

    assert not Settings().provider_diagnostics_enabled


def test_native_invalid_request_maps_safe_public_error():
    import dspy

    from app.agui.live_coordinator import _code_for_exception

    code, message = _code_for_exception(dspy.LMInvalidRequestError("private prompt"))
    assert code == "provider_request_rejected"
    assert "private" not in message


@pytest.mark.parametrize(
    "echo", ["12345678", "1234-5678", "private reasoning", "private result"]
)
def test_partial_and_transformed_echoes_are_not_retained(echo):
    body = {
        "messages": [
            {
                "content": "Account 12345678 private result",
                "reasoning_content": "private reasoning",
            }
        ]
    }
    payload = {
        "error": {
            "message": f"Invalid messages: {echo}",
            "code": echo,
            "request_id": f"req-{echo}",
            "loc": ["body", "messages", 12345678],
        }
    }
    facts = rejection_facts(json.dumps(payload).encode(), body, ())
    assert echo not in json.dumps(facts)
    assert "details" not in facts
    assert facts["codes"] == []
    assert facts["locations"] == ["body.messages"]


def test_request_ids_cannot_echo_request_fragments():
    from app.agent.provider_diagnostics import _request_id

    assert _request_id("req-deadbeef") == "req-deadbeef"
    assert (
        _request_id(
            "req-12345678", body={"messages": [{"content": "Account 12345678"}]}
        )
        is None
    )
    assert _request_id("req-private-account") is None
    assert _request_id("req-deadbeef", ("deadbeef",)) is None
    assert _request_id("req-deadbeef", ("sk-deadbeef-token",)) is None


def test_rejection_traversal_is_bounded():
    assert rejection_facts(b"x" * 262145, {}, ())["truncated"]
    payload = {
        "error": {
            "error": {
                "error": {
                    "error": {
                        "error": {
                            "error": {
                                "error": {"error": {"error": {"message": "secret"}}}
                            }
                        }
                    }
                }
            }
        }
    }
    assert rejection_facts(json.dumps(payload).encode(), {}, ())["truncated"]


def test_parallel_attempts_cannot_exceed_the_budget(monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from types import SimpleNamespace

    from dspy.lm15 import ConfigurationError

    from app.agent.provider_diagnostics import DiagnosticTransport

    transport = DiagnosticTransport(enabled=False, limit=1)
    attempts = []
    monkeypatch.setattr(
        transport.native, "stream", lambda request: attempts.append(True)
    )

    def invoke(_):
        try:
            transport.stream(SimpleNamespace())
            return True
        except ConfigurationError:
            return False

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(invoke, range(8)))
        assert sum(results) == 1
        assert len(attempts) == transport.calls == 1
    finally:
        transport.close()
