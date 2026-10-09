import subprocess
from pathlib import Path

import pytest

from app.contracts.cards import make_card, settled_cards


@pytest.mark.parametrize("name", ["inline-card", "message-feedback"])
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
