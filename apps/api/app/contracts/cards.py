"""Validated message-scoped projections of authoritative public state."""

import json
from typing import Any, cast
from urllib.parse import urlsplit

from app.contracts.inline_card import InlineCard
from app.kernel.content_safety import scrub_json_strings


def make_card(
    kind: str, data: dict[str, Any], *, run_id: str, message_id: str
) -> dict[str, Any] | None:
    payload = {key: value for key, value in data.items() if key != "schemaVersion"}
    envelope = scrub_json_strings(
        {
            "schemaVersion": 2,
            "kind": kind,
            "runId": run_id,
            "messageId": message_id,
            "data": payload,
        }
    )
    try:
        return cast(
            dict[str, Any],
            InlineCard.model_validate(envelope).model_dump(
                mode="json", exclude_none=True
            ),
        )
    except ValueError:
        return None


def settled_cards(
    state: dict[str, Any], *, run_id: str, message_id: str
) -> list[dict[str, Any]]:
    result = []
    sources = [
        {
            "sourceId": str(source["id"])[:128],
            "title": str(source.get("title", "Source"))[:240],
            "domain": (
                urlsplit(source.get("uri") or "").hostname
                or str(source.get("sourceType", "source"))
            )[:120],
        }
        for source in state.get("sources", [])[:12]
    ]
    for cycle, tool in enumerate(state.get("toolCalls", [])):
        if tool.get("name") != "web_search":
            continue
        matching = [
            source
            for source in state.get("sources", [])
            if source.get("toolCallId") == tool.get("id")
        ][:12]
        try:
            preview = json.loads(tool.get("inputPreview") or "{}")
            query = (
                preview.get("query", "Restored web search")
                if isinstance(preview, dict)
                else "Restored web search"
            )
        except (TypeError, ValueError):
            query = "Restored web search"
        card = make_card(
            "web-search",
            {
                "query": query,
                "results": [
                    {
                        "sourceId": str(source["id"])[:128],
                        "title": str(source.get("title", "Source"))[:240],
                        "domain": (
                            urlsplit(source.get("uri") or "").hostname or "source"
                        )[:240],
                    }
                    for source in matching
                ],
                "searching": False,
                "visibleResults": len(matching),
                "cycle": cycle,
            },
            run_id=run_id,
            message_id=message_id,
        )
        if card:
            result.append(card)
    if sources:
        card = make_card(
            "sources", {"sources": sources}, run_id=run_id, message_id=message_id
        )
        if card:
            result.append(card)
    for artifact in state.get("artifacts", []):
        if artifact.get("status") != "ready":
            continue
        card = make_card(
            "artifact",
            {
                key: artifact[key]
                for key in ("id", "name", "mediaType", "downloadUrl")
                if key in artifact
            },
            run_id=run_id,
            message_id=message_id,
        )
        if card:
            result.append(card)
    return result[:32]
