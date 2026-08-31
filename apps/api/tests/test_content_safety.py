"""Emission-time secret scrubbing: pattern precision + every choke point.

The public/private boundary is structural for payloads (schema, history
safety); these tests pin the content-level guarantee for free text: a secret
that reaches a public field, tool output preview, artifact, or legacy
snapshot is masked before it crosses the API boundary — while model
observations and tool behavior stay untouched.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import dspy
import pytest

from app.agent.callbacks import AgUiRunCallback
from app.agent.engine import AgentRunContext, DspyAgentEngine, _map_result
from app.agent.instrumented import instrument_tool
from app.agent.signature import AgentSignature
from app.agent.tooling import create_dspy_tool
from app.agent.tools.report import WriteReportTool
from app.agui.event_bus import RunEventBus
from app.api.threads import _safe_bootstrap_agent_state
from app.contracts.domain import ToolCompleted, ToolStarted
from app.services.artifact_storage import LocalArtifactStorage
from app.services.content_safety import (
    StreamingScrubber,
    scrub_json_strings,
    scrub_public_lines,
    scrub_public_text,
)
from tests.helpers.scripted_lm import ScriptedLM, submit_call

CTX = AgentRunContext(thread_id="t-scrub", run_id="r-scrub")

# Canonical samples for every pattern in content_safety.
SECRET_SAMPLES = [
    "sk-proj-4ZqY9wF2xQ7bR1mK3nD8vT5c",  # OpenAI-style
    "sk-or-v1-7c9d2e4f6a8b0c1d3e5f7a9b",  # OpenRouter-style
    "sk-ant-api03-Xy7qP9wL2mK5nB8vC4xD",  # Anthropic-style
    "AKIAIOSFODNN7EXAMPLE",  # AWS access key id
    "AIzaAbCdEf0123456789AbCdEf0123456789AbC",  # Google API key (AIza + 35)
    "ghp_16C7e42F292c6912E7710c838347Ae178B4a",  # GitHub classic
    "github_pat_11A0B1C2d3E4f5G6h7I8j9k0L",  # GitHub fine-grained
    "xoxb-123456789012-ABCDEFabcdef",  # Slack bot token
    # JWT
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
    "dozjgNryP4J3jVNH_doctor_2XdF3oXm5cC4bW7yY8r9tU0iO1pQ",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA7f\n"
    "-----END RSA PRIVATE KEY-----",
    "Authorization: Bearer AbCdEf123456789012345678",  # Bearer header
    "export API_KEY=Z9y8x7w6v5u4t3s2r1q0",  # assignment
    'password = "Sup3rS3cr3tV4lu3H3re0123"',  # assignment
]


@pytest.mark.parametrize("sample", SECRET_SAMPLES)
def test_known_secret_formats_are_masked(sample: str) -> None:
    scrubbed = scrub_public_text(f"prefix {sample} suffix")
    assert sample not in scrubbed
    assert "[redacted]" in scrubbed
    assert "prefix" in scrubbed and "suffix" in scrubbed


def test_scrubbed_json_stays_valid_json() -> None:
    encoded = json.dumps(
        {"command": "curl -H 'Authorization: Bearer AbCdEf123456789012345678' x"}
    )
    scrubbed = scrub_public_text(encoded)
    parsed = json.loads(scrubbed)
    assert "AbCdEf123456789012345678" not in scrubbed
    assert parsed["command"].startswith("curl")


@pytest.mark.parametrize(
    "safe",
    [
        # Ordinary hyphenated prose must never match the sk- pattern.
        "task-oriented-design-patterns-for-engineers",
        "We discussed risk-adjusted returns and key decisions.",
        "The sha256 checksum is "
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "sha256:0cdce66d25d747c9d97d84b6bfa2b8d2b6b7d3b0f4c2a1e0d9c8b7a6f5e4d3",
        "GET https://api.example.com/v1/projects?id=42&page=2",
        "os.environ['PATH'] and sys.executable stay readable",
        "run failed with error code agent_no_output",
    ],
)
def test_high_precision_patterns_do_not_scrub_ordinary_text(safe: str) -> None:
    assert scrub_public_text(safe) == safe


def test_scrub_lines_and_nested_json_strings() -> None:
    lines = scrub_public_lines(["sk-proj-4ZqY9wF2xQ7bR1mK3nD8vT5c", "plain"])
    assert lines[0] == "[redacted]"
    assert lines[1] == "plain"

    nested = scrub_json_strings(
        {"steps": [{"publicSummary": "key sk-abc123def456ghi789jkl here"}], "n": 3}
    )
    assert nested["steps"][0]["publicSummary"] == "key [redacted] here"
    assert nested["n"] == 3


def _prediction_with_secrets() -> dspy.Prediction:
    return dspy.Prediction(
        answer="Use key sk-proj-4ZqY9wF2xQ7bR1mK3nD8vT5c to call the API.",
        process_summary="Authored the token ghp_16C7e42F292c6912E7710c838347Ae178B4a.",
        key_decisions=["Called the endpoint with AKIAIOSFODNN7EXAMPLE."],
        caveats=["The password = Sup3rS3cr3tV4lu3H3re0123 may expire."],
        termination_reason="submit",
    )


def test_map_result_scrubs_every_public_text_field() -> None:
    result = _map_result(_prediction_with_secrets())

    assert result.status == "completed"
    assert "sk-proj" not in (result.answer or "")
    assert "ghp_" not in (result.process_summary or "")
    assert "AKIA" not in result.key_decisions[0]
    assert "Sup3r" not in result.caveats[0]
    assert "[redacted]" in (result.answer or "")
    assert "Use key" in (result.answer or "")  # surrounding text survives


async def test_engine_run_scrubs_model_echoed_secrets() -> None:
    """End to end: even if a tool observation is echoed into the answer, the
    settled result that reaches the coordinator is scrubbed (the model's own
    observation is deliberately left intact)."""

    def leaky(query: str) -> str:
        """Return a credential in tool output."""
        return "token=sk-abc123def456ghi789jklmno"

    def factory() -> dspy.ReActV2:
        return dspy.ReActV2(
            AgentSignature, tools=[create_dspy_tool(leaky)], max_iters=4
        )

    engine = DspyAgentEngine(
        program_factory=factory,
        lm=ScriptedLM(
            [
                [{"name": "leaky", "args": {"query": "creds"}}],
                [
                    submit_call(
                        answer="Here it is: sk-abc123def456ghi789jklmno",
                        summary="Echoed sk-abc123def456ghi789jklmno back.",
                    )
                ],
            ]
        ),  # type: ignore[arg-type]
        adapter=dspy.JSONAdapter(),
    )
    result = await engine.run(
        user_request="hand me the token", history=None, context=CTX
    )

    assert result.status == "completed"
    assert "sk-abc123" not in (result.answer or "")
    assert "sk-abc123" not in (result.process_summary or "")
    assert "[redacted]" in (result.answer or "")


async def test_callback_previews_scrub_raw_tool_output() -> None:
    """Tool output previews are the one place raw tool results cross the wire."""
    bus = RunEventBus(asyncio.get_running_loop())
    callback = AgUiRunCallback(bus=bus)

    def shell(command: str) -> str:
        """Run a command for the test."""
        return "ok"

    tool = create_dspy_tool(shell)

    callback.on_tool_start(
        "call-1",
        tool,
        {
            "kwargs": {
                "command": "curl -H 'Authorization: Bearer AbCdEf01234567890123' x"
            }
        },
    )
    started = await bus.next()
    assert isinstance(started, ToolStarted)
    # arguments_json must stay valid, parseable JSON with secrets masked.
    parsed_args = json.loads(started.arguments_json)
    assert "AbCdEf01234567890123" not in started.arguments_json
    assert "AbCdEf01234567890123" not in started.input_preview
    assert "command" in parsed_args

    callback.on_tool_end("call-1", "AKIAIOSFODNN7EXAMPLE found in file")
    completed = await bus.next()
    assert isinstance(completed, ToolCompleted)
    assert "AKIA" not in completed.output_preview
    assert "[redacted]" in completed.output_preview


async def test_instrument_tool_scrubs_previews_but_not_return_values() -> None:
    bus = RunEventBus(asyncio.get_running_loop())

    def leak() -> str:
        """Leak a credential in output."""
        return "found sk-abc123def456ghi789jklmno"

    wrapped = instrument_tool(leak, bus)
    value = wrapped()

    # Behavior preserved: the model still receives the real tool output.
    assert value == "found sk-abc123def456ghi789jklmno"

    started = await bus.next()
    completed = await bus.next()
    assert isinstance(started, ToolStarted)
    assert isinstance(completed, ToolCompleted)
    assert "sk-abc123" not in completed.output_preview
    assert "[redacted]" in completed.output_preview


async def test_report_artifact_content_is_scrubbed(tmp_path: Path) -> None:
    bus = RunEventBus(asyncio.get_running_loop())
    storage = LocalArtifactStorage(tmp_path)
    tool = WriteReportTool(
        storage=storage, bus=bus, thread_id="t-scrub", max_bytes=10_000
    )

    result = tool(
        title="Deployment credentials",
        content="Use sk-proj-4ZqY9wF2xQ7bR1mK3nD8vT5c for deploys.",
    )

    files = list(tmp_path.rglob("*.md"))
    assert len(files) == 1
    assert "sk-proj" not in files[0].read_text()
    assert "[redacted]" in files[0].read_text()
    assert "sk-proj" not in result


def test_bootstrap_legacy_state_is_scrubbed_on_read() -> None:
    state = {
        "schemaVersion": 1,
        "threadId": "t-legacy",
        "run": {"id": "r-1", "status": "completed", "toolCallCount": 1},
        "steps": [
            {
                "id": "s",
                "phase": "synthesis",
                "title": "T",
                "status": "completed",
                "toolCallIds": [],
                "sourceIds": [],
                "artifactIds": [],
                "publicSummary": "used sk-abc123def456ghi789jklmno",
            }
        ],
        "decisions": [],
        "toolCalls": [
            {
                "id": "c",
                "name": "bash",
                "status": "completed",
                "outputPreview": "AKIAIOSFODNN7EXAMPLE",
            }
        ],
        "sources": [],
        "artifacts": [],
        "metrics": {"toolCallCount": 1},
        "caveats": ["token ghp_16C7e42F292c6912E7710c838347Ae178B4a"],
    }

    safe = _safe_bootstrap_agent_state(state, thread_id="t-legacy")

    assert safe is not None
    assert safe["steps"][0]["publicSummary"] == "used [redacted]"
    assert safe["toolCalls"][0]["outputPreview"] == "[redacted]"
    assert safe["caveats"] == ["token [redacted]"]


# --- Streaming scrubber -------------------------------------------------------
#
# The scrubber must never emit a fragment of a secret that is still arriving,
# and the concatenation of everything it emits must equal the batch scrub of
# the full text, for every possible delta split.

_STREAM_SECRET_SAMPLES = [
    "sk-proj-abc123def456ghi789jkl",
    "AKIAIOSFODNN7EXAMPLE",
    "ghp_AbCdEf1234567890123456789",
    "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0."
    "dozjgNryP4J3jVNH_doctor_2XdF3oXm5cC4bW7yY8r9tU0iO1pQ",
    "-----BEGIN RSA PRIVATE KEY-----\nMIIEpAIBAAKCAQEA7f\n"
    "-----END RSA PRIVATE KEY-----",
    "password = Sup3rS3cretAbCdEf123456",
    "Bearer AbCdEf123456789012345678",
]


def _stream_in_chunks(text: str, chunk: int, *, holdback: int = 8) -> list[str]:
    scrubber = StreamingScrubber(holdback_chars=holdback)
    emitted = []
    for index in range(0, len(text), chunk):
        emitted.append(scrubber.push(text[index : index + chunk]))
    emitted.append(scrubber.flush())
    return emitted


@pytest.mark.parametrize("secret", _STREAM_SECRET_SAMPLES)
@pytest.mark.parametrize("chunk", [1, 3, 5, 17])
def test_stream_scrubber_never_emits_secret_fragments(secret: str, chunk: int) -> None:
    """Every delta split of a secret-bearing text is safe and equivalent."""
    text = f"Here is the credential {secret} and then ordinary prose follows."
    pieces = _stream_in_chunks(text, chunk)

    joined = "".join(pieces)
    # 1. No fragment of the raw secret ever crosses the boundary.
    for piece in pieces:
        assert secret[:6] not in piece
        assert secret not in piece
    # 2. Streamed output equals the batch scrub of the full text.
    assert joined == scrub_public_text(text)
    assert secret not in joined
    assert "[redacted]" in joined


def test_stream_scrubber_masks_whole_secret_arriving_in_one_delta() -> None:
    scrubber = StreamingScrubber()
    secret = "sk-abc123def456ghi789jklmno"
    text = (
        f"prefix {secret} suffix with plenty of trailing characters "
        "to pass the holdback window."
    )

    emitted = [scrubber.push(delta) for delta in (text, "")]
    emitted.append(scrubber.flush())

    joined = "".join(emitted)
    assert "sk-abc123" not in joined
    assert "[redacted]" in joined
    assert joined == scrub_public_text(text)


def test_stream_scrubber_holds_partial_anchor_prefixes() -> None:
    """``...the pass`` must not stream before ``word = <secret>`` can arrive."""
    scrubber = StreamingScrubber(holdback_chars=8)
    secret = "Sup3rS3cretAbCdEf123456"

    first = scrubber.push("The pass")
    assert first == ""  # could still continue into "password"

    second = scrubber.push(f"word = {secret}")
    assert "pass" not in second

    remainder = scrubber.flush()
    joined = first + second + remainder
    assert joined == scrub_public_text(f"The password = {secret}")
    assert "[redacted]" in joined
    assert secret not in joined


def test_stream_scrubber_holds_pem_body_until_end_line() -> None:
    body = "MIIEpAIBAAKCAQEA7f3Zk9"
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        f"{body}\n"
        "-----END RSA PRIVATE KEY-----\n"
        "The key was processed.\n"
    )

    pieces = _stream_in_chunks(text, 7, holdback=8)

    # The PEM body never streams out before the END line resolves it.
    for piece in pieces[:-1]:
        assert body not in piece
        assert "MIIEpA" not in piece
    assert "".join(pieces) == scrub_public_text(text)
    assert "[redacted]" in "".join(pieces)
    assert body not in "".join(pieces)


def test_stream_scrubber_benign_anchor_lags_then_flushes() -> None:
    """A benign anchor word only lags; the flushed text is unchanged."""
    scrubber = StreamingScrubber(holdback_chars=8)
    text = "Bearer of good news arrived today for the whole team."

    pieces = []
    for index in range(0, len(text), 5):
        pieces.append(scrubber.push(text[index : index + 5]))
    pieces.append(scrubber.flush())

    joined = "".join(pieces)
    assert joined == text  # benign text survives unmasked
    assert "[redacted]" not in joined
    # The anchor held the stream back mid-field instead of streaming past it.
    assert not any("Bearer of good" in piece for piece in pieces[:-1])


def test_stream_scrubber_streams_clean_text_with_progress() -> None:
    """Text without any anchor streams incrementally, not only at flush."""
    scrubber = StreamingScrubber(holdback_chars=8)
    text = "Ordinary streaming text without any credential-like words at all."

    emitted = []
    for index in range(0, len(text), 4):
        emitted.append(scrubber.push(text[index : index + 4]))

    # Before flush, at least the earliest confirmed window has been emitted.
    assert "".join(emitted).startswith("Ordinary")
    assert len("".join(emitted)) > 8


def test_stream_scrubber_resumes_streaming_after_secret_is_masked() -> None:
    """A masked secret does not permanently stall the rest of the field."""
    scrubber = StreamingScrubber(holdback_chars=8)
    secret = "AKIAIOSFODNN7EXAMPLE"
    tail = " and then the answer keeps streaming normally onward. "

    scrubber.push(f"key {secret}")
    before_flush = "".join(scrubber.push(tail))
    flushed = scrubber.flush()

    joined = before_flush + flushed
    assert secret not in joined
    assert "[redacted]" in joined
    # Prose after the mask streamed out before the flush.
    assert "streaming normally" in before_flush


def test_stream_scrubber_flush_is_idempotent() -> None:
    scrubber = StreamingScrubber()
    scrubber.push("some pending text with a tail")
    first = scrubber.flush()
    assert scrubber.flush() == ""
    assert first
