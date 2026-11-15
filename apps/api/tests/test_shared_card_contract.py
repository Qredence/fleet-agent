import logging
import subprocess
from pathlib import Path

import pytest

from app.contracts.cards import make_card, settled_cards


@pytest.mark.parametrize(
    "name", ["inline-card", "message-feedback", "thread-bootstrap"]
)
def test_generated_models_are_fresh(name):
    root = Path(__file__).resolve().parents[3]
    result = subprocess.run(
        [
            "uv",
            "run",
            "datamodel-codegen",
            "--input",
            str(root / f"packages/contracts/{name}.schema.json"),
            "--input-file-type",
            "jsonschema",
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--target-python-version",
            "3.13",
            "--use-union-operator",
            "--enum-field-as-literal",
            "all",
            "--disable-timestamp",
            "--formatters",
            "ruff-check",
            "ruff-format",
        ],
        cwd=root / "apps/api",
        capture_output=True,
        text=True,
        check=True,
    )
    assert (
        result.stdout
        == (root / f"apps/api/app/contracts/{name.replace('-', '_')}.py").read_text()
    )


def test_cards_restore_settled_search_with_source_references():
    cards = settled_cards(
        {
            "toolCalls": [
                {
                    "id": "tool-search",
                    "name": "web_search",
                    "inputPreview": '{"query":{"type":"string","chars":4}}',
                }
            ],
            "sources": [
                {
                    "id": "source-doc",
                    "title": "Evidence",
                    "uri": "https://example.com/doc",
                    "toolCallId": "tool-search",
                }
            ],
            "artifacts": [],
        },
        run_id="run",
        message_id="message",
    )
    search = next(card for card in cards if card["kind"] == "web-search")
    assert search["data"]["searching"] is False
    assert search["data"]["results"][0]["sourceId"] == "source-doc"
    assert search["runId"] == "run" and search["messageId"] == "message"
    assert make_card("future", {}, run_id="run", message_id="message") is None


def test_cards_handle_malformed_uris_recent_sources_long_ids_and_logging(
    caplog: pytest.LogCaptureFixture,
):
    long_id = "id-" + ("x" * 200)
    many_sources = [
        {
            "id": f"src-{idx}",
            "title": f"Source {idx}",
            "uri": (
                "http://[invalid-ipv6" if idx == 14 else f"https://s{idx}.example.com"
            ),
            "sourceType": "web",
            "toolCallId": "tool-1",
        }
        for idx in range(15)
    ]
    truncated_preview = (
        '{"extra":"val","query":{"type":"string","chars":19},"more":"abc…'
    )
    cards = settled_cards(
        {
            "toolCalls": [
                {
                    "id": "tool-1",
                    "name": "web_search",
                    "inputPreview": truncated_preview,
                },
                {
                    "id": "tool-2",
                    "name": "web_search",
                    "inputPreview": f'{{"query":"{"q" * 300}"}}',
                },
            ],
            "sources": many_sources,
            "artifacts": [
                {
                    "id": long_id,
                    "status": "ready",
                    "name": "n" * 300,
                    "mediaType": "text/markdown",
                    "downloadUrl": "/api/artifacts/ok_123",
                }
            ],
        },
        run_id=long_id,
        message_id=long_id,
    )

    web_cards = [card for card in cards if card["kind"] == "web-search"]
    assert len(web_cards) == 2
    assert web_cards[0]["data"]["query"] == {"type": "string", "chars": 19}
    assert len(web_cards[1]["data"]["query"]) == 240

    sources_card = next(card for card in cards if card["kind"] == "sources")
    assert [s["sourceId"] for s in sources_card["data"]["sources"]] == [
        f"src-{idx}" for idx in range(3, 15)
    ]
    assert sources_card["data"]["sources"][-1]["domain"] == "web"

    artifact_card = next(card for card in cards if card["kind"] == "artifact")
    assert len(artifact_card["runId"]) == 128
    assert len(artifact_card["messageId"]) == 128
    assert len(artifact_card["data"]["id"]) == 128

    with caplog.at_level(logging.WARNING):
        dropped = make_card(
            "future", {"secret": "sk-proj-secret12345"}, run_id="r", message_id="m"
        )
    assert dropped is None
    assert "Dropped invalid inline card kind=future" in caplog.text
    assert "sk-proj" not in caplog.text
